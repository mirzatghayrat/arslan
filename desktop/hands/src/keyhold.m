// The key hold (spec 2026-10-08-0157 §6.3 step 4, Q2): while Hands borrows the front, every key
// event the USER makes is held, in order, and replayed into their window afterwards, so no key is
// lost or misdirected. Hands' own events (and those of the processes it started: agent-desktop)
// pass, and so do the replays (tagged in kCGEventSourceUserData).
//
// One session event tap at the head, on its own thread with its own run loop. Mouse events are
// only watched (never held): the last time the user moved or clicked, for "yield to the user"
// (§6.3 step 9) and the takeover's pause (§6.4). Nothing about a key's identity is kept beyond
// the held events themselves; the probe reports types and source pids only.
//
// Built by build.rs with the system clang, like capture.m.
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Carbon/Carbon.h>
#include <libproc.h>
#include <mach/mach_time.h>
#include <pthread.h>
#include <stdatomic.h>

static const int64_t HANDS_MAGIC = 0x41524c4e;   // "ARLN": Hands' replays
#define HELD_MAX 4096                             // past this the island asks the user to pause

static CFMachPortRef tap;
static pthread_t tap_thread;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static bool armed;                                // guarded by lock
static uint64_t armed_until;                      // guarded by lock: mach time; 0 = no deadline
static _Atomic int expired_count;                 // holds the tap thread released on its own
static CGEventRef held[HELD_MAX];                 // guarded by lock
static int held_count;                            // guarded by lock
static int held_overflow;                         // guarded by lock: events that did not fit
static pid_t own_pid;
static _Atomic uint64_t last_user_key, last_user_mouse;   // mach_absolute_time
static _Atomic int disabled_count;

typedef struct { uint64_t at; int type; int pid; int parent; bool ours; bool held; } Seen;
static Seen seen[64];                             // guarded by lock
static int seen_total;                            // guarded by lock

static double now_ms_since(uint64_t then) {
    if (then == 0) return -1;
    static mach_timebase_info_data_t base;
    if (base.denom == 0) mach_timebase_info(&base);
    uint64_t delta = mach_absolute_time() - then;
    return (double)delta * base.numer / base.denom / 1e6;
}

static pid_t parent_of(pid_t pid) {
    struct proc_bsdinfo info;
    if (pid <= 0 || proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, sizeof info) != sizeof info) return -1;
    return (pid_t)info.pbi_ppid;
}

static bool is_key(CGEventType type) {
    return type == kCGEventKeyDown || type == kCGEventKeyUp || type == kCGEventFlagsChanged;
}

static CGEventRef on_event(CGEventTapProxy proxy, CGEventType type, CGEventRef event, void *info) {
    if (type == kCGEventTapDisabledByTimeout || type == kCGEventTapDisabledByUserInput) {
        atomic_fetch_add(&disabled_count, 1);
        if (tap) CGEventTapEnable(tap, true);
        return event;
    }
    int64_t tag = CGEventGetIntegerValueField(event, kCGEventSourceUserData);
    pid_t pid = (pid_t)CGEventGetIntegerValueField(event, kCGEventSourceUnixProcessID);
    pid_t parent = pid > 0 && pid != own_pid ? parent_of(pid) : -1;
    bool ours = tag == HANDS_MAGIC || pid == own_pid || parent == own_pid;
    bool key = is_key(type);
    if (!ours) atomic_store(key ? &last_user_key : &last_user_mouse, mach_absolute_time());
    bool hold = false;
    pthread_mutex_lock(&lock);
    if (key && !ours && armed) {
        if (held_count < HELD_MAX) {
            held[held_count++] = CGEventCreateCopy(event);
            hold = true;
        } else {
            held_overflow++;            // never dropped silently: passed through, and counted
        }
    }
    seen[seen_total % 64] = (Seen){mach_absolute_time(), (int)type, pid, parent, ours, hold};
    seen_total++;
    pthread_mutex_unlock(&lock);
    return hold ? NULL : event;
}

int hands_keyhold_release(void);

// A hold never outlives its borrow: past its deadline the tap's own thread gives the keys back,
// whatever the rest of Hands is doing (stuck, crashed in a request, killed by Stop).
static void watchdog(CFRunLoopTimerRef timer, void *info) {
    pthread_mutex_lock(&lock);
    bool overdue = armed && armed_until != 0 && mach_absolute_time() > armed_until;
    pthread_mutex_unlock(&lock);
    if (overdue) {
        atomic_fetch_add(&expired_count, 1);
        hands_keyhold_release();
    }
}

static void *run_tap(void *unused) {
    CFRunLoopSourceRef source = CFMachPortCreateRunLoopSource(NULL, tap, 0);
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopCommonModes);
    CFRunLoopTimerRef timer = CFRunLoopTimerCreate(NULL, CFAbsoluteTimeGetCurrent() + 0.1, 0.1, 0, 0,
                                                   watchdog, NULL);
    CFRunLoopAddTimer(CFRunLoopGetCurrent(), timer, kCFRunLoopCommonModes);
    CGEventTapEnable(tap, true);
    CFRunLoopRun();
    return NULL;
}

// 0 running; 1 the tap could not be created (no permission for it).
int hands_keyhold_start(void) {
    if (tap) return 0;
    own_pid = getpid();
    CGEventMask mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)
        | CGEventMaskBit(kCGEventFlagsChanged) | CGEventMaskBit(kCGEventMouseMoved)
        | CGEventMaskBit(kCGEventLeftMouseDown) | CGEventMaskBit(kCGEventLeftMouseUp)
        | CGEventMaskBit(kCGEventRightMouseDown) | CGEventMaskBit(kCGEventRightMouseUp)
        | CGEventMaskBit(kCGEventOtherMouseDown) | CGEventMaskBit(kCGEventOtherMouseUp)
        | CGEventMaskBit(kCGEventLeftMouseDragged) | CGEventMaskBit(kCGEventRightMouseDragged)
        | CGEventMaskBit(kCGEventScrollWheel);
    CFMachPortRef created = CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                                             kCGEventTapOptionDefault, mask, on_event, NULL);
    if (!created) return 1;
    tap = created;
    pthread_create(&tap_thread, NULL, run_tap, NULL);
    return 0;
}

// From now on the user's key events are held, for at most `max_ms` (then given back regardless).
void hands_keyhold_arm(double max_ms) {
    static mach_timebase_info_data_t base;
    if (base.denom == 0) mach_timebase_info(&base);
    pthread_mutex_lock(&lock);
    armed = true;
    armed_until = max_ms > 0 ? mach_absolute_time() + (uint64_t)(max_ms * 1e6 * base.denom / base.numer) : 0;
    pthread_mutex_unlock(&lock);
}

// Replay everything held, in order, through the normal event path (the HID tap, so input methods
// compose as usual); keys the user makes during the replay queue behind it. Then stop holding.
// Returns how many were replayed.
int hands_keyhold_release(void) {
    int replayed = 0;
    for (;;) {
        pthread_mutex_lock(&lock);
        if (held_count == 0) {
            armed = false;
            armed_until = 0;
            pthread_mutex_unlock(&lock);
            return replayed;
        }
        CGEventRef event = held[0];
        memmove(held, held + 1, sizeof(CGEventRef) * (size_t)(held_count - 1));
        held_count--;
        pthread_mutex_unlock(&lock);
        CGEventSetIntegerValueField(event, kCGEventSourceUserData, HANDS_MAGIC);
        CGEventPost(kCGHIDEventTap, event);
        CFRelease(event);
        replayed++;
    }
}

// Milliseconds since the user's last key / mouse event (-1: none seen since the tap started).
double hands_keyhold_user_key_age_ms(void) { return now_ms_since(atomic_load(&last_user_key)); }
double hands_keyhold_user_mouse_age_ms(void) { return now_ms_since(atomic_load(&last_user_mouse)); }
bool hands_keyhold_secure_input(void) { return IsSecureEventInputEnabled(); }

// For the Q2 probe: JSON, malloc'd (free with hands_keyhold_free).
char *hands_keyhold_probe(void) {
    @autoreleasepool {
        NSMutableArray *events = [NSMutableArray array];
        pthread_mutex_lock(&lock);
        int count = seen_total < 64 ? seen_total : 64;
        for (int i = seen_total - count; i < seen_total; i++) {
            Seen s = seen[i % 64];
            [events addObject:@{@"ago_ms": @(now_ms_since(s.at)), @"type": @(s.type), @"pid": @(s.pid),
                                @"parent": @(s.parent), @"ours": @(s.ours), @"held": @(s.held)}];
        }
        NSDictionary *out = @{
            @"tap": @(tap != NULL), @"armed": @(armed), @"held": @(held_count),
            @"overflow": @(held_overflow), @"seen_total": @(seen_total), @"seen": events,
            @"own_pid": @(own_pid), @"disabled": @(atomic_load(&disabled_count)),
            @"expired": @(atomic_load(&expired_count)),
            @"secure_input": @(IsSecureEventInputEnabled()),
            @"listen_access": @(CGPreflightListenEventAccess()),
            @"post_access": @(CGPreflightPostEventAccess()),
            @"idle_hid_s": @(CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateHIDSystemState,
                                                                     kCGAnyInputEventType)),
            @"idle_session_s": @(CGEventSourceSecondsSinceLastEventType(kCGEventSourceStateCombinedSessionState,
                                                                         kCGAnyInputEventType)),
            @"user_key_age_ms": @(hands_keyhold_user_key_age_ms()),
            @"user_mouse_age_ms": @(hands_keyhold_user_mouse_age_ms()),
        };
        pthread_mutex_unlock(&lock);
        NSData *data = [NSJSONSerialization dataWithJSONObject:out options:0 error:nil];
        char *text = malloc(data.length + 1);
        memcpy(text, data.bytes, data.length);
        text[data.length] = 0;
        return text;
    }
}

void hands_keyhold_free(char *text) { free(text); }
