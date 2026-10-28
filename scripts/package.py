"""Package only runtime files for App Service; never include local secrets."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
if not (root / "frontend/dist/index.html").is_file():
    raise SystemExit("Build the frontend first: cd frontend && npm run build")
output = root / "artifacts"
output.mkdir(exist_ok=True)
with ZipFile(output / "app.zip", "w", ZIP_DEFLATED) as archive:
    paths = [root / "requirements.txt"]
    paths.extend((root / "backend").rglob("*.py"))
    paths.extend(path for path in (root / "frontend/dist").rglob("*") if path.is_file())
    for path in sorted(paths):
        archive.write(path, path.relative_to(root).as_posix())
print(output / "app.zip")
