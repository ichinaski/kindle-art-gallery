/*
 * evtap: read Linux input devices for the art gallery.
 *
 *   evtap [-t MS] [-g DEV]... [DEV]...          stream mode
 *   evtap -p SECS [-g DEV]... [DEV]...          probe mode
 *
 * -g DEV opens DEV with EVIOCGRAB, so nobody else (X, the paused Kindle UI) gets
 * its events. A plain DEV is read without grabbing. The grab is released by the
 * kernel when this process exits, even if it crashes.
 *
 * Stream mode writes raw 16-byte input_event records (32-bit ARM layout) to
 * stdout, plus a heartbeat record (all 0xFF bytes) every MS milliseconds (default
 * 250), so the reader has a clock. It exits when stdout closes. It exits with
 * status 2 if a requested grab fails.
 *
 * Probe mode prints device info, whether each grab worked, and the decoded events
 * for SECS seconds, as text. A failed grab is reported but does not stop it.
 *
 * Records are handled as raw bytes: on 32-bit ARM the kernel sends 16-byte
 * events, while musl's struct input_event is 24 bytes (64-bit time_t).
 */
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define REC 16
#define MAXDEV 8

static long long now_ms(void) {
  struct timespec ts;
  clock_gettime(CLOCK_MONOTONIC, &ts);
  return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static int write_all(const unsigned char *b, size_t n) {
  while (n) {
    ssize_t w = write(1, b, n);
    if (w < 0) {
      if (errno == EINTR) continue;
      return -1;
    }
    b += w;
    n -= (size_t)w;
  }
  return 0;
}

static const char *abs_name(int code) {
  switch (code) {
  case ABS_X: return "X";
  case ABS_Y: return "Y";
  case ABS_PRESSURE: return "PRESSURE";
  case ABS_MT_SLOT: return "MT_SLOT";
  case ABS_MT_TOUCH_MAJOR: return "MT_TOUCH_MAJOR";
  case ABS_MT_POSITION_X: return "MT_POSITION_X";
  case ABS_MT_POSITION_Y: return "MT_POSITION_Y";
  case ABS_MT_TRACKING_ID: return "MT_TRACKING_ID";
  case ABS_MT_PRESSURE: return "MT_PRESSURE";
  default: return NULL;
  }
}

static void describe(int fd, const char *path) {
  char name[128] = "?";
  ioctl(fd, EVIOCGNAME(sizeof(name)), name);
  printf("device %s: %s\n", path, name);
  static const int codes[] = {ABS_X, ABS_Y, ABS_MT_SLOT, ABS_MT_POSITION_X,
                              ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID};
  for (unsigned i = 0; i < sizeof(codes) / sizeof(codes[0]); i++) {
    struct input_absinfo ai;
    if (ioctl(fd, EVIOCGABS(codes[i]), &ai) == 0)
      printf("  abs %-15s min=%d max=%d\n", abs_name(codes[i]), ai.minimum, ai.maximum);
  }
}

static void put_rec(unsigned char *r, int type, int code, int value) {
  memset(r, 0, REC);
  r[8] = type & 0xFF; r[9] = (type >> 8) & 0xFF;
  r[10] = code & 0xFF; r[11] = (code >> 8) & 0xFF;
  r[12] = value & 0xFF; r[13] = (value >> 8) & 0xFF;
  r[14] = (value >> 16) & 0xFF; r[15] = (value >> 24) & 0xFF;
}

/* The kernel only reports coordinates that change, so a reader that starts late
 * does not know where each slot was. Send the current per-slot positions first,
 * as ordinary events, so the reader starts with the same state as the kernel. */
static int send_mt_state(int fd) {
  enum { SLOTS = 16 };
  struct { unsigned code; int values[SLOTS]; } req;
  int xs[SLOTS], ys[SLOTS];
  struct input_absinfo slot;
  req.code = ABS_MT_POSITION_X;
  if (ioctl(fd, EVIOCGMTSLOTS(sizeof(req)), &req) < 0) return 0;
  memcpy(xs, req.values, sizeof(xs));
  req.code = ABS_MT_POSITION_Y;
  if (ioctl(fd, EVIOCGMTSLOTS(sizeof(req)), &req) < 0) return 0;
  memcpy(ys, req.values, sizeof(ys));
  if (ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &slot) < 0) slot.value = 0;
  unsigned char out[REC * (SLOTS * 3 + 2)], *r = out;
  for (int i = 0; i < SLOTS; i++) {
    put_rec(r, EV_ABS, ABS_MT_SLOT, i); r += REC;
    put_rec(r, EV_ABS, ABS_MT_POSITION_X, xs[i]); r += REC;
    put_rec(r, EV_ABS, ABS_MT_POSITION_Y, ys[i]); r += REC;
  }
  put_rec(r, EV_ABS, ABS_MT_SLOT, slot.value); r += REC;
  put_rec(r, EV_SYN, SYN_REPORT, 0); r += REC;
  return write_all(out, (size_t)(r - out));
}

static void usage(void) {
  fprintf(stderr, "usage: evtap [-t MS | -p SECS] [-g DEV]... [DEV]...\n");
  exit(1);
}

int main(int argc, char **argv) {
  struct pollfd pfd[MAXDEV];
  const char *paths[MAXDEV];
  int n = 0, beat = 250, probe = -1; /* -1: stream mode */

  signal(SIGPIPE, SIG_DFL);
  for (int i = 1; i < argc; i++) {
    const char *a = argv[i];
    int grab = 0;
    if (!strcmp(a, "-t") && i + 1 < argc) { beat = atoi(argv[++i]); continue; }
    if (!strcmp(a, "-p") && i + 1 < argc) { probe = atoi(argv[++i]); continue; }
    if (!strcmp(a, "-g") && i + 1 < argc) { grab = 1; a = argv[++i]; }
    else if (a[0] == '-') usage();
    if (n == MAXDEV) usage();

    int fd = open(a, O_RDONLY | O_NONBLOCK);
    if (fd < 0) {
      fprintf(stderr, "evtap: cannot open %s: %s\n", a, strerror(errno));
      if (grab && probe < 0) return 2;
      continue;
    }
    if (probe >= 0) describe(fd, a);
    if (grab) {
      if (ioctl(fd, EVIOCGRAB, 1) != 0) {
        if (probe >= 0) {
          printf("  grab: FAILED (%s)\n", strerror(errno));
        } else {
          fprintf(stderr, "evtap: cannot grab %s: %s\n", a, strerror(errno));
          return 2;
        }
      } else if (probe >= 0) {
        printf("  grab: ok\n");
      }
    }
    if (grab && probe < 0 && send_mt_state(fd)) return 0;
    pfd[n].fd = fd;
    pfd[n].events = POLLIN;
    paths[n] = a;
    n++;
  }
  if (n == 0) usage();
  if (beat < 20) beat = 20;
  fflush(stdout);

  unsigned char buf[REC * 64];
  unsigned char hb[REC];
  memset(hb, 0xFF, sizeof(hb));
  long long start = now_ms(), next_beat = start + beat;
  long events = 0, lifts = 0, max_slot = 0;

  for (;;) {
    long long t = now_ms();
    int timeout;
    if (probe >= 0) {
      if (t >= start + probe * 1000LL) break;
      timeout = (int)(start + probe * 1000LL - t);
    } else {
      if (t >= next_beat) {
        if (write_all(hb, REC)) return 0;
        next_beat = t + beat;
      }
      timeout = (int)(next_beat - t);
    }
    int r = poll(pfd, n, timeout);
    if (r < 0 && errno != EINTR) { perror("evtap: poll"); return 1; }
    if (r <= 0) continue;

    for (int i = 0; i < n; i++) {
      if (!(pfd[i].revents & POLLIN)) continue;
      ssize_t got = read(pfd[i].fd, buf, sizeof(buf));
      if (got <= 0) continue;
      got -= got % REC;
      if (probe < 0) {
        if (write_all(buf, (size_t)got)) return 0;
        continue;
      }
      for (ssize_t off = 0; off < got; off += REC) {
        const unsigned char *e = buf + off;
        int type = e[8] | e[9] << 8, code = e[10] | e[11] << 8;
        int value = (int)((unsigned)e[12] | (unsigned)e[13] << 8 | (unsigned)e[14] << 16 |
                          (unsigned)e[15] << 24);
        if (type == EV_SYN) continue;
        events++;
        if (type == EV_ABS && code == ABS_MT_TRACKING_ID && value < 0) lifts++;
        if (type == EV_ABS && code == ABS_MT_SLOT && value > max_slot) max_slot = value;
        double secs = (now_ms() - start) / 1000.0;
        if (type == EV_ABS && abs_name(code))
          printf("%7.3f %s ABS %s %d\n", secs, paths[i], abs_name(code), value);
        else if (type == EV_KEY)
          printf("%7.3f %s KEY %d %s\n", secs, paths[i], code,
                 value == 1 ? "down" : value == 0 ? "up" : "repeat");
        else
          printf("%7.3f %s type=%d code=%d value=%d\n", secs, paths[i], type, code, value);
      }
      fflush(stdout);
    }
  }
  printf("summary: %ld events, %ld finger lifts (MT_TRACKING_ID -1), highest slot %ld\n",
         events, lifts, max_slot);
  return 0;
}
