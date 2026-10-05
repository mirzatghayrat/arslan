/* Runs a program with macOS responsibility disclaimed, so it is its own
 * responsible process and holds no Accessibility grant: how the Hands contract
 * check sees PERM_DENIED. Private SPI, used by Apple's own launchers. */
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>
extern int responsibility_spawnattrs_setdisclaim(posix_spawnattr_t *, int);
extern char **environ;
int main(int argc, char **argv) {
  posix_spawnattr_t a; posix_spawnattr_init(&a);
  responsibility_spawnattrs_setdisclaim(&a, 1);
  pid_t p; int rc = posix_spawn(&p, argv[1], NULL, &a, argv + 1, environ);
  if (rc) { perror("spawn"); return 1; }
  int st; waitpid(p, &st, 0); return WEXITSTATUS(st);
}
