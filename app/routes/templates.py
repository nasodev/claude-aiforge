import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/templates")

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEMPLATES_DIR = PROJECT_ROOT / "workspace-templates"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"


def _validate_name(name: str, base_dir: Path) -> Path | None:
    """Validate name doesn't escape base_dir via path traversal. Returns resolved path or None."""
    target = (base_dir / name).resolve()
    if not str(target).startswith(str(base_dir.resolve()) + "/"):
        return None
    return target


def find_env_files(template_dir: Path) -> list[Path]:
    """Find .env.example or .env files recursively in template dir."""
    results = sorted(template_dir.rglob(".env.example"))
    if not results:
        results = sorted(template_dir.rglob(".env"))
    return results


def parse_env_file(env_path: Path) -> list[dict]:
    """Parse .env.example or .env into list of {key, default, comment}."""
    result = []
    if not env_path.exists():
        return result

    comment_buffer = ""
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            comment_buffer = ""
            continue
        if stripped.startswith("#"):
            comment_buffer = stripped.lstrip("# ").strip()
            continue
        if "=" in stripped:
            key, _, default = stripped.partition("=")
            result.append({
                "key": key.strip(),
                "default": default.strip(),
                "comment": comment_buffer,
            })
            comment_buffer = ""
    return result


def find_readme(template_dir: Path) -> Path | None:
    """Find README.md in template dir (root first, then subdirs)."""
    root_readme = template_dir / "README.md"
    if root_readme.exists():
        return root_readme
    for p in template_dir.rglob("README.md"):
        return p
    return None


def _has_any_env_file(template_dir: Path) -> bool:
    """Check if any .env.example or .env exists without scanning the full tree."""
    for _ in template_dir.rglob(".env.example"):
        return True
    for _ in template_dir.rglob(".env"):
        return True
    return False


def discover_templates() -> list[dict]:
    """Scan workspace-templates/ for template folders."""
    if not TEMPLATES_DIR.exists():
        return []

    templates = []
    for d in sorted(TEMPLATES_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue

        has_claude = (d / ".claude").exists()
        has_env = _has_any_env_file(d)
        readme = find_readme(d)
        copied = (WORKSPACE_DIR / d.name).exists()

        description = ""
        if readme:
            first_line = readme.read_text().strip().split("\n")[0]
            description = first_line.lstrip("# ").strip()

        templates.append({
            "name": d.name,
            "has_claude": has_claude,
            "has_env": has_env,
            "copied": copied,
            "description": description,
        })
    return templates


def copy_template_to_workspace(name: str) -> Path:
    """Copy template to workspace, excluding .env.example and .env."""
    src = TEMPLATES_DIR / name
    dst = WORKSPACE_DIR / name
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    if dst.exists():
        shutil.rmtree(dst)

    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(".env.example", ".env"),
    )
    return dst


def write_env_file(dest_dir: Path, env_path: str, env_vars: dict[str, str]):
    """Write .env file at the relative path from form values."""
    target = (dest_dir / env_path).resolve()
    if not str(target).startswith(str(dest_dir.resolve()) + "/"):
        return  # path traversal attempt
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in env_vars.items()]
    target.write_text("\n".join(lines) + "\n")


@router.get("/")
def list_templates(request: Request):
    templates = discover_templates()
    return request.app.state.templates.TemplateResponse(
        "templates.html",
        {"request": request, "templates": templates, "page": "templates"},
    )


@router.get("/{name}/setup")
def template_setup(request: Request, name: str):
    src = _validate_name(name, TEMPLATES_DIR)
    if not src or not src.is_dir():
        return RedirectResponse("/templates", status_code=303)

    env_files = find_env_files(src)
    env_sections = []
    for ef in env_files:
        rel_path = ef.relative_to(src)
        env_sections.append({
            "path": str(rel_path),
            "vars": parse_env_file(ef),
        })

    already_exists = (WORKSPACE_DIR / name).exists()
    dest_path = str(WORKSPACE_DIR / name)

    return request.app.state.templates.TemplateResponse(
        "template_setup.html",
        {
            "request": request,
            "name": name,
            "env_sections": env_sections,
            "already_exists": already_exists,
            "dest_path": dest_path,
            "page": "templates",
        },
    )


@router.post("/{name}/copy")
async def copy_template(request: Request, name: str):
    src = _validate_name(name, TEMPLATES_DIR)
    if not src or not src.is_dir():
        return RedirectResponse("/templates", status_code=303)

    # Copy template files (offload blocking I/O)
    dest = await asyncio.to_thread(copy_template_to_workspace, name)

    # Collect env vars from form, grouped by env_path
    form_data = await request.form()

    # Gather env paths
    env_paths = {}
    for k, v in form_data.items():
        if k.startswith("env_path_"):
            idx = k[len("env_path_"):]
            env_paths[idx] = v

    # Gather env vars per section
    for idx, env_path in env_paths.items():
        prefix = f"env_{idx}__"
        env_vars = {}
        for k, v in form_data.items():
            if k.startswith(prefix):
                real_key = k[len(prefix):]
                env_vars[real_key] = v
        if env_vars:
            # Convert .env.example path to .env
            out_path = env_path.replace(".env.example", ".env")
            if not out_path.endswith(".env"):
                out_path = str(Path(env_path).parent / ".env")
            write_env_file(dest, out_path, env_vars)

    return RedirectResponse("/templates", status_code=303)
