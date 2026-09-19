"""Exercise an installed SkillKit wheel as a new skill author, outside the checkout.

Run with Python 3.11+ after ``python -m build`` (which builds the wheel from
the sdist). ``--work-dir`` chooses a parent for the temporary, clean environment.
Only the wheel is installed; neither the checkout nor an editable install is
available to the consumer's imports.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from email.parser import BytesParser
from pathlib import Path

NAMES = ("garden-watering", "quelle-heure", "window", "travaux")

# Run this probe with the consumer interpreter in isolated mode. Comparing
# every packaged file catches a locale or module available only in the checkout.
PROBE = r'''
import importlib
from importlib.metadata import distribution, entry_points, version
from importlib.resources import files
import json
from pathlib import Path
import sys
import zipfile

wheel, package, distribution_name, group, entry_name, kit_version = sys.argv[1:]
module = importlib.import_module(package)
assert Path(module.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()), module.__file__
assert version("thalovant-skillkit") == kit_version
dist = distribution(distribution_name)
origin = json.loads(dist.read_text("direct_url.json") or "{}")
assert not origin.get("dir_info", {}).get("editable"), origin
root = files(package)
with zipfile.ZipFile(wheel) as archive:
    resources = [name for name in archive.namelist()
                 if name.startswith(package + "/") and not name.endswith("/")]
    assert resources, "wheel contains no package files"
    for name in resources:
        relative = name[len(package) + 1:]
        assert root.joinpath(relative).read_bytes() == archive.read(name), name
entry, = entry_points(group=group, name=entry_name)
target = entry.load()
assert callable(target)
if group == "opm.skill":
    skill = target()
    assert skill.preview_reply("", "en-US").startswith("This is the ")
    assert skill.preview_reply("", "fr-FR").startswith("Voici la compétence ")
print(f"Installed {distribution_name}: entry point and {len(resources)} package files verified.")
'''


def run(*command: str | Path, cwd: Path, env: dict[str, str]) -> None:
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(list(map(str, command)), cwd=cwd, env=env, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, help="also compare the source archive")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1],
                        help="source inventory to compare as data, never an import path")
    parser.add_argument("--work-dir", type=Path, help="parent for temporary consumer files")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("generated skills require Python 3.11 or newer")
    wheel = args.wheel.resolve(strict=True)
    source = args.source.resolve(strict=True)
    sdist = args.sdist.resolve(strict=True) if args.sdist else None
    with zipfile.ZipFile(wheel) as archive:
        metadata, = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        package_metadata = BytesParser().parsebytes(archive.read(metadata))
    if package_metadata["Name"] != "thalovant-skillkit":
        parser.error("--wheel must name a thalovant-skillkit wheel")
    kit_version = package_metadata["Version"]
    if args.work_dir:
        args.work_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="skillkit-consumer-", dir=args.work_dir) as temporary:
        work = Path(temporary).resolve()
        environment = work / "venv"
        venv.EnvBuilder(with_pip=True).create(environment)
        bin_dir = environment / ("Scripts" if os.name == "nt" else "bin")
        python = bin_dir / ("python.exe" if os.name == "nt" else "python")
        cli = bin_dir / ("thalovant-skillkit.exe" if os.name == "nt" else "thalovant-skillkit")
        # Keep package-index/cache configuration, but discard import/install
        # overrides that could redirect this verification to a developer's copy.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("PYTHON") and key not in {
                   "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_CONSTRAINT",
                   "PIP_BUILD_CONSTRAINT", "VIRTUAL_ENV",
               }}
        env.update({"VIRTUAL_ENV": str(environment), "PYTHONNOUSERSITE": "1"})
        for name in ("CONFIG", "DATA", "CACHE", "STATE"):
            directory = work / "xdg" / name.lower()
            directory.mkdir(parents=True)
            env[f"XDG_{name}_HOME"] = str(directory)
        constraints = work / "constraints.txt"
        constraints.write_text(f"thalovant-skillkit=={kit_version}\n", encoding="utf-8")
        run(python, "-I", "-m", "pip", "install", "--pre", "--constraint", constraints,
            wheel, "pytest", "build", cwd=work, env=env)
        probe = work / "probe.py"
        probe.write_text(PROBE, encoding="utf-8")
        run(python, "-I", probe, wheel, "thalovant_skillkit", "thalovant-skillkit",
            "console_scripts", "thalovant-skillkit", kit_version, cwd=work, env=env)
        run(cli, "--help", cwd=work, env=env)
        # The wheel alone cannot reveal a file omitted from both archive and
        # installation. Let the installed checker compare the source inventory.
        artifact_options = ("--sdist", sdist) if sdist else ()
        run(cli, "check-artifacts", source, "--package", "thalovant_skillkit",
            "--wheel", wheel, *artifact_options, cwd=work, env=env)

        for name in NAMES:
            project = work / f"thalovant-skill-{name}"
            run(cli, "new", name, "--directory", project, cwd=work, env=env)
            locale = project / f"thalovant_skill_{name.replace('-', '_')}" / "locale"
            dialog = f"dialog/{name.replace('-', '.')}.dialog"
            (locale / "regional.json").write_text(json.dumps({
                "version": 1,
                "locales": {"en-CA": {"source": "en-US", "overrides": {
                    dialog: "This Canadian example keeps the shared vocabulary.\n",
                }}},
            }), encoding="utf-8")
            run(cli, "locales", project, "--write", cwd=work, env=env)
            run(cli, "locales", project, cwd=work, env=env)
            run(cli, "check", project, cwd=work, env=env)
            # Build through the source archive, then install the generated
            # wheel with its declared test extra and the tested Kit version.
            run(python, "-I", "-m", "build", project, cwd=work, env=env)
            skill_wheel, = (project / "dist").glob("*.whl")
            skill_sdist, = (project / "dist").glob("*.tar.gz")
            run(cli, "check-artifacts", project, "--wheel", skill_wheel,
                "--sdist", skill_sdist, cwd=work, env=env)
            run(python, "-I", "-m", "pip", "install", "--pre", "--constraint", constraints,
                f"{skill_wheel}[test]", cwd=work, env=env)
            run(python, "-I", probe, skill_wheel, f"thalovant_skill_{name.replace('-', '_')}",
                f"thalovant-skill-{name}", "opm.skill", f"thalovant-skill-{name}.thalovant",
                kit_version, cwd=work, env=env)
            # importlib mode prevents pytest from adding the generated source
            # directory to sys.path; the suite exercises the installed wheel.
            run(python, "-I", "-m", "pytest", "--import-mode=importlib", "-q", project / "test",
                cwd=work, env=env)
        run(python, "-I", "-m", "pip", "check", cwd=work, env=env)
        print(f"SkillKit {kit_version}: installed-wheel consumer checks passed "
              f"for {len(NAMES)} skills.")


if __name__ == "__main__":
    main()
