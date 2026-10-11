// Which desktop an app's windows are on (spec 2026-10-08-0157 §15 A18): the raw lists; spaces.rs
// counts. Accessibility lists only windows on the desktops (Spaces) being shown; the window server
// lists them all — and also the closed windows an app keeps (ordered out, never released: Finder's,
// Music's, the main window of an app that keeps running). Both kinds are "not on screen" there, with
// the same keys (measured on a real Mac, 2026-10-11; ScreenCaptureKit's isActive is false for both
// too). AppKit's list of windows ordered in on every desktop tells them apart: a window on another
// desktop is in it, a closed one is not.
//
// Public API only (CGWindowListCopyWindowInfo, +[NSWindow windowNumbersWithOptions:]). Bounds,
// layer and on-screen state need no permission; window titles are not read.
//
// Built by build.rs with the system clang, like capture.m.
#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>

// An ordinary window of app `pid`: layer 0, at least 100 x 100 points, not fully transparent.
static BOOL ordinary(NSDictionary *window, int pid) {
    if ([window[(id)kCGWindowOwnerPID] intValue] != pid) return NO;
    if ([window[(id)kCGWindowLayer] intValue] != 0) return NO;
    NSNumber *alpha = window[(id)kCGWindowAlpha];
    if (alpha != nil && alpha.doubleValue <= 0) return NO;
    CGRect bounds;
    NSDictionary *box = window[(id)kCGWindowBounds];
    if (box == nil || !CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)box, &bounds)) return NO;
    return bounds.size.width >= 100 && bounds.size.height >= 100;
}

// App `pid`'s ordinary windows: each one's number and whether it is on screen, up to `cap`.
// `shown_only`: only those on screen (a much cheaper list: about 0.4 ms against 3-4 ms for every
// window, measured). Returns how many there are (more than `cap`: the rest were left out), or -1.
int hands_app_window_list(int pid, int shown_only, uint32_t *numbers, uint8_t *on_screen, int cap) {
    @autoreleasepool {
        CGWindowListOption option = shown_only ? kCGWindowListOptionOnScreenOnly : kCGWindowListOptionAll;
        CFArrayRef listed = CGWindowListCopyWindowInfo(option, kCGNullWindowID);
        if (listed == NULL) return -1;
        int count = 0;
        for (NSDictionary *window in (NSArray *)CFBridgingRelease(listed)) {
            if (!ordinary(window, pid)) continue;
            if (count < cap) {
                numbers[count] = [window[(id)kCGWindowNumber] unsignedIntValue];
                on_screen[count] = [window[(id)kCGWindowIsOnscreen] boolValue] ? 1 : 0;
            }
            count++;
        }
        return count;
    }
}

// The numbers of every window ordered in on any desktop, all apps, up to `cap`. Asked on the main
// thread (Hands' NSApplication loop serves it), like glow.m. Returns how many there are, or -1 when
// AppKit did not answer within 500 ms.
int hands_ordered_in_everywhere(uint32_t *numbers, int cap) {
    __block NSArray<NSNumber *> *listed = nil;
    dispatch_semaphore_t done = dispatch_semaphore_create(0);
    void (^ask)(void) = ^{
        listed = [NSWindow windowNumbersWithOptions:NSWindowNumberListAllApplications | NSWindowNumberListAllSpaces];
        dispatch_semaphore_signal(done);
    };
    if ([NSThread isMainThread]) {
        ask();
    } else {
        dispatch_async(dispatch_get_main_queue(), ask);
    }
    if (dispatch_semaphore_wait(done, dispatch_time(DISPATCH_TIME_NOW, 500 * NSEC_PER_MSEC)) != 0) return -1;
    if (listed == nil) return -1;
    int count = 0;
    for (NSNumber *number in listed) {
        if (count < cap) numbers[count] = number.unsignedIntValue;
        count++;
    }
    return count;
}

// Every ordinary window on screen (layer 0, at least 100 x 100 points, not fully transparent), all
// apps, front to back: its number and its app's pid, up to `cap`. What a visit to another desktop
// must find on screen again when it comes back (src/visit.rs). Returns how many, or -1.
int hands_shown_windows(uint32_t *numbers, int32_t *owners, int cap) {
    @autoreleasepool {
        CFArrayRef listed = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID);
        if (listed == NULL) return -1;
        int count = 0;
        for (NSDictionary *window in (NSArray *)CFBridgingRelease(listed)) {
            int pid = [window[(id)kCGWindowOwnerPID] intValue];
            if (!ordinary(window, pid)) continue;
            if (count < cap) {
                numbers[count] = [window[(id)kCGWindowNumber] unsignedIntValue];
                owners[count] = pid;
            }
            count++;
        }
        return count;
    }
}
