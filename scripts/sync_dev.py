from collections.abc import Sequence
import subprocess


def run(args: Sequence[str]) -> None:
    subprocess.run(args, check=True)  # noqa: S603


def main() -> None:
    run(["git", "fetch", "github"])
    run(["git", "switch", "dev"])
    run(["git", "reset", "--hard", "github/main"])
    run(["git", "push", "--force-with-lease", "github", "dev"])


if __name__ == "__main__":
    main()
