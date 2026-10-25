/** Read the current git branch once per directory and cache it.
 *
 * The status bar renders on every keystroke; spawning git from render would be
 * both slow and wasteful. The workspace is fixed for the process lifetime, so a
 * single lookup is enough. */
const cache = new Map<string, string | null>();

export function readGitBranch(cwd: string): string | null {
    if (cache.has(cwd)) return cache.get(cwd)!;

    let branch: string | null = null;
    try {
        const result = Bun.spawnSync(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            { cwd, stdout: "pipe", stderr: "pipe" },
        );
        if (result.exitCode === 0) {
            const name = new TextDecoder().decode(result.stdout).trim();
            // Detached HEAD reports "HEAD"; there is no branch to show.
            branch = name && name !== "HEAD" ? name : null;
        }
    } catch {
        branch = null;
    }

    cache.set(cwd, branch);
    return branch;
}
