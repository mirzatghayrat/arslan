// The edge glow (spec 2026-10-08-0157 §6.6): while Hands borrows the front (short) or has taken
// the screen over (steady), every display shows a thin glowing edge, so the user always knows the
// keyboard and pointer are not theirs right now.
//
// One borderless, non-activating panel per screen: clicks go through it, it sits above full-screen
// apps and on every Space, and it is left out of every screen capture (NSWindowSharingNone), so
// Hands' own window screenshots never contain it. All AppKit work runs on the main thread, which
// Hands' NSApplication loop serves.
//
// Built by build.rs with the system clang, like capture.m.
#import <AppKit/AppKit.h>
#import <QuartzCore/QuartzCore.h>

static NSMutableArray<NSPanel *> *panels;   // main thread only

static NSPanel *edge_panel(NSScreen *screen, NSColor *color) {
    NSPanel *panel = [[NSPanel alloc] initWithContentRect:screen.frame
                                                styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                                  backing:NSBackingStoreBuffered
                                                    defer:NO];
    panel.opaque = NO;
    panel.backgroundColor = NSColor.clearColor;
    panel.hasShadow = NO;
    panel.ignoresMouseEvents = YES;
    panel.level = NSScreenSaverWindowLevel;
    panel.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorFullScreenAuxiliary | NSWindowCollectionBehaviorStationary
        | NSWindowCollectionBehaviorIgnoresCycle;
    panel.sharingType = NSWindowSharingNone;
    panel.releasedWhenClosed = NO;
    NSView *view = panel.contentView;
    view.wantsLayer = YES;
    CALayer *edge = [CALayer layer];
    edge.frame = view.bounds;
    edge.autoresizingMask = kCALayerWidthSizable | kCALayerHeightSizable;
    edge.borderWidth = 3;
    edge.borderColor = color.CGColor;
    edge.shadowColor = color.CGColor;
    edge.shadowOpacity = 0.9;
    edge.shadowRadius = 22;
    edge.shadowOffset = CGSizeZero;
    [view.layer addSublayer:edge];
    panel.alphaValue = 0;
    return panel;
}

// Show the glow on every display in the colour (r, g, b in 0…1).
void hands_glow_show(double r, double g, double b) {
    dispatch_async(dispatch_get_main_queue(), ^{
        for (NSPanel *panel in panels) [panel orderOut:nil];
        panels = [NSMutableArray array];
        NSColor *color = [NSColor colorWithSRGBRed:r green:g blue:b alpha:1];
        for (NSScreen *screen in NSScreen.screens) {
            NSPanel *panel = edge_panel(screen, color);
            [panel orderFrontRegardless];
            [panels addObject:panel];
            [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
                context.duration = 0.15;
                panel.animator.alphaValue = 1;
            } completionHandler:nil];
        }
    });
}

// Fade the glow out and take it away.
void hands_glow_hide(void) {
    dispatch_async(dispatch_get_main_queue(), ^{
        NSArray<NSPanel *> *going = panels;     // a show right after builds its own
        panels = nil;
        [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
            context.duration = 0.2;
            for (NSPanel *panel in going) panel.animator.alphaValue = 0;
        } completionHandler:^{
            for (NSPanel *panel in going) [panel orderOut:nil];
        }];
    });
}
