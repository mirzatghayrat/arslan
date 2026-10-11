// Which desktop an app's windows are on (spec 2026-10-08-0157 §15 A18). Accessibility lists only
// windows on the desktops (Spaces) being shown; the window server lists them all. An app whose
// windows the window server has but none of them on screen has them on another desktop.
//
// Public API only (CGWindowListCopyWindowInfo). Bounds, layer and on-screen state need no
// permission; window titles are not read.
//
// Built by build.rs with the system clang, like capture.m.
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>

// Counts app `pid`'s ordinary windows (layer 0, at least 100 x 100 points, not fully transparent):
// on screen, and elsewhere (on a desktop not being shown, or minimized). 0 on success.
int hands_app_windows(int pid, int *on_screen, int *elsewhere) {
    @autoreleasepool {
        *on_screen = 0;
        *elsewhere = 0;
        CFArrayRef listed = CGWindowListCopyWindowInfo(kCGWindowListOptionAll, kCGNullWindowID);
        if (listed == NULL) return 1;
        NSArray *windows = CFBridgingRelease(listed);
        for (NSDictionary *window in windows) {
            if ([window[(id)kCGWindowOwnerPID] intValue] != pid) continue;
            if ([window[(id)kCGWindowLayer] intValue] != 0) continue;
            NSNumber *alpha = window[(id)kCGWindowAlpha];
            if (alpha != nil && alpha.doubleValue <= 0) continue;
            CGRect bounds;
            NSDictionary *box = window[(id)kCGWindowBounds];
            if (box == nil || !CGRectMakeWithDictionaryRepresentation((__bridge CFDictionaryRef)box, &bounds)) continue;
            if (bounds.size.width < 100 || bounds.size.height < 100) continue;
            if ([window[(id)kCGWindowIsOnscreen] boolValue]) {
                (*on_screen)++;
            } else {
                (*elsewhere)++;
            }
        }
        return 0;
    }
}
