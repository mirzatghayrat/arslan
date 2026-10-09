// One window's screenshot, for Hands v2's look (spec 2026-10-08-0157 §4.2, §15 A8).
//
// ScreenCaptureKit, because CGWindowListCreateImage is obsoleted in the macOS 15 SDK.
// The window must belong to `pid` (checked against the window list, not trusted from the
// caller); 0 for `window_id` means that app's frontmost normal window. The image is a
// JPEG in memory, base64 in the returned JSON; nothing is written anywhere.
//
// Entry point: hands_capture (refuses below macOS 14). Built by build.rs with the system clang (no Rust crate: every dependency of Hands runs
// with its grants). The C entry point returns a malloc'd JSON string the caller frees with
// hands_capture_free:
//   {"ok":true,"window_id":N,"onscreen":B,"frame":{"x","y","width","height"},"scale":S,
//    "width":W,"height":H,"mime":"image/jpeg","data":"<base64>"}
//   {"ok":false,"code":"…","message":"…"}
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <ImageIO/ImageIO.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>

static char *json_of(NSDictionary *object) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:object options:0 error:nil];
    if (!data) return strdup("{\"ok\":false,\"code\":\"capture_failed\",\"message\":\"could not encode\"}");
    char *out = malloc(data.length + 1);
    memcpy(out, data.bytes, data.length);
    out[data.length] = 0;
    return out;
}

static char *refusal(NSString *code, NSString *message) {
    return json_of(@{@"ok": @NO, @"code": code, @"message": message});
}

// The app's windows from the window server, front to back: normal windows (layer 0) only.
static NSArray<NSDictionary *> *windows_of(pid_t pid) {
    NSMutableArray *found = [NSMutableArray array];
    CFArrayRef list = CGWindowListCopyWindowInfo(kCGWindowListOptionAll | kCGWindowListExcludeDesktopElements,
                                                 kCGNullWindowID);
    if (!list) return found;
    for (NSDictionary *info in (__bridge NSArray *)list) {
        if ([info[(id)kCGWindowOwnerPID] intValue] == pid && [info[(id)kCGWindowLayer] intValue] == 0) {
            [found addObject:info];
        }
    }
    CFRelease(list);
    return found;
}

char *hands_capture_window(int32_t pid, uint32_t window_id, int32_t max_edge) API_AVAILABLE(macos(14.0));

char *hands_capture(int32_t pid, uint32_t window_id, int32_t max_edge) {
    if (@available(macOS 14.0, *)) return hands_capture_window(pid, window_id, max_edge);
    return refusal(@"needs_macos_14", @"window screenshots need macOS 14 or later");
}

char *hands_capture_window(int32_t pid, uint32_t window_id, int32_t max_edge) {
    @autoreleasepool {
        if (!CGPreflightScreenCaptureAccess()) {
            return refusal(@"screen_recording_off", @"Arslan Hands is not allowed to record the screen");
        }
        NSArray<NSDictionary *> *windows = windows_of(pid);
        NSDictionary *chosen = nil;
        for (NSDictionary *info in windows) {
            BOOL onscreen = [info[(id)kCGWindowIsOnscreen] boolValue];
            if (window_id ? [info[(id)kCGWindowNumber] unsignedIntValue] == window_id : onscreen) {
                chosen = info;
                break;
            }
        }
        if (!chosen && window_id == 0 && windows.count) chosen = windows.firstObject;
        if (!chosen) {
            return refusal(@"window_not_found",
                           window_id ? @"that window is not one of this app's windows" : @"this app has no window");
        }
        uint32_t wanted = [chosen[(id)kCGWindowNumber] unsignedIntValue];

        __block SCWindow *target = nil;
        __block NSString *failure = nil;
        dispatch_semaphore_t listed = dispatch_semaphore_create(0);
        [SCShareableContent getShareableContentExcludingDesktopWindows:YES
                                                   onScreenWindowsOnly:NO
                                                     completionHandler:^(SCShareableContent *content, NSError *error) {
            if (error) failure = error.localizedDescription;
            for (SCWindow *window in content.windows) {
                if (window.windowID == wanted && window.owningApplication.processID == pid) {
                    target = window;
                    break;
                }
            }
            dispatch_semaphore_signal(listed);
        }];
        if (dispatch_semaphore_wait(listed, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC))) {
            return refusal(@"capture_failed", @"the window list did not answer in time");
        }
        if (!target) {
            return refusal(failure ? @"capture_failed" : @"window_not_capturable",
                           failure ?: @"the window server does not offer this window for capture");
        }

        SCContentFilter *filter = [[SCContentFilter alloc] initWithDesktopIndependentWindow:target];
        CGRect frame = target.frame;
        CGFloat scale = filter.pointPixelScale > 0 ? filter.pointPixelScale : 1;
        CGFloat longest = MAX(frame.size.width, frame.size.height) * scale;
        CGFloat shrink = longest > max_edge ? max_edge / longest : 1;
        SCStreamConfiguration *config = [[SCStreamConfiguration alloc] init];
        config.width = MAX(1, (size_t)lround(frame.size.width * scale * shrink));
        config.height = MAX(1, (size_t)lround(frame.size.height * scale * shrink));
        config.showsCursor = NO;
        config.ignoreShadowsSingleWindow = YES;

        __block CGImageRef image = NULL;
        dispatch_semaphore_t captured = dispatch_semaphore_create(0);
        [SCScreenshotManager captureImageWithFilter:filter
                                      configuration:config
                                  completionHandler:^(CGImageRef result, NSError *error) {
            if (result) image = CGImageRetain(result);
            else failure = error.localizedDescription;
            dispatch_semaphore_signal(captured);
        }];
        if (dispatch_semaphore_wait(captured, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC))) {
            return refusal(@"capture_failed", @"the capture did not finish in time");
        }
        if (!image) return refusal(@"capture_failed", failure ?: @"no image");

        NSMutableData *jpeg = [NSMutableData data];
        CGImageDestinationRef out = CGImageDestinationCreateWithData((__bridge CFMutableDataRef)jpeg,
                                                                     CFSTR("public.jpeg"), 1, NULL);
        NSDictionary *options = @{(__bridge NSString *)kCGImageDestinationLossyCompressionQuality: @0.8};
        CGImageDestinationAddImage(out, image, (__bridge CFDictionaryRef)options);
        BOOL written = CGImageDestinationFinalize(out);
        CFRelease(out);
        size_t width = CGImageGetWidth(image), height = CGImageGetHeight(image);
        CGImageRelease(image);
        if (!written) return refusal(@"capture_failed", @"could not encode the image");

        return json_of(@{
            @"ok": @YES,
            @"window_id": @(wanted),
            @"title": chosen[(id)kCGWindowName] ?: @"",
            // Off the current screen (another Space, behind a full-screen app, minimized): the
            // image is whatever the window last drew, possibly incomplete or out of date.
            @"onscreen": @([chosen[(id)kCGWindowIsOnscreen] boolValue]),
            // Points, screen coordinates (top-left origin), as accessibility reports them.
            @"frame": @{@"x": @(frame.origin.x), @"y": @(frame.origin.y),
                        @"width": @(frame.size.width), @"height": @(frame.size.height)},
            // Image pixels per point: an element at screen point P is at (P - frame.origin) * scale.
            @"scale": @((double)width / MAX(frame.size.width, 1)),
            @"width": @(width), @"height": @(height),
            @"mime": @"image/jpeg",
            @"data": [jpeg base64EncodedStringWithOptions:0],
        });
    }
}

void hands_capture_free(char *json) { free(json); }
