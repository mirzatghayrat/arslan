// Can VoiceProcessingIO be made to run on built-in mic + built-in speakers at all?
//  A. AVAudioEngine: pin the AU to the aggregate BEFORE enabling VP
//  B. raw AUVoiceIO AudioUnit with CurrentDevice = aggregate / mic / speakers, input render callback level meter
import AVFoundation
import AudioToolbox
import CoreAudio
import Foundation

func prop<T>(_ obj: AudioObjectID, _ sel: AudioObjectPropertySelector, _ zero: T) -> T {
    var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var v = zero; var size = UInt32(MemoryLayout<T>.size)
    AudioObjectGetPropertyData(obj, &addr, 0, nil, &size, &v); return v
}
func allDevices() -> [(AudioDeviceID, String, String)] {
    var addr = AudioObjectPropertyAddress(mSelector: kAudioHardwarePropertyDevices, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var size: UInt32 = 0
    AudioObjectGetPropertyDataSize(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size)
    var ids = [AudioDeviceID](repeating: 0, count: Int(size) / MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &ids)
    return ids.map { id in
        let name = prop(id, kAudioObjectPropertyName, nil as Unmanaged<CFString>?)?.takeUnretainedValue() as String? ?? "?"
        let uid = prop(id, kAudioDevicePropertyDeviceUID, nil as Unmanaged<CFString>?)?.takeUnretainedValue() as String? ?? "?"
        return (id, name, uid)
    }
}
func auDevice(_ au: AudioUnit) -> AudioDeviceID {
    var d: AudioDeviceID = 0; var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    AudioUnitGetProperty(au, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &d, &size); return d
}
func pin(_ au: AudioUnit, _ id: AudioDeviceID) -> OSStatus {
    var d = id
    return AudioUnitSetProperty(au, kAudioOutputUnitProperty_CurrentDevice, kAudioUnitScope_Global, 0, &d, UInt32(MemoryLayout<AudioDeviceID>.size))
}
let devs = allDevices()
let mic = devs.first { $0.1 == "MacBook Pro Microphone" }!, spk = devs.first { $0.1 == "MacBook Pro Speakers" }!
let desc: [String: Any] = [
    kAudioAggregateDeviceNameKey: "arslan-voice-probe", kAudioAggregateDeviceUIDKey: "com.arslantest.voiceprobe.agg",
    kAudioAggregateDeviceIsPrivateKey: 1, kAudioAggregateDeviceMainSubDeviceKey: spk.2,
    kAudioAggregateDeviceSubDeviceListKey: [[kAudioSubDeviceUIDKey: spk.2], [kAudioSubDeviceUIDKey: mic.2]],
]
var agg: AudioDeviceID = 0
print("aggregate:", AudioHardwareCreateAggregateDevice(desc as CFDictionary, &agg), agg)
defer { AudioHardwareDestroyAggregateDevice(agg) }
let variant = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "engine_pin_first"

if variant == "engine_pin_first" {
    let engine = AVAudioEngine(); let input = engine.inputNode
    print("pin before VP:", pin(input.audioUnit!, agg), "->", auDevice(input.audioUnit!))
    do { try input.setVoiceProcessingEnabled(true); print("VP on; device now", auDevice(input.audioUnit!)) } catch { print("VP failed", error) }
    print("pin after VP:", pin(input.audioUnit!, agg), "->", auDevice(input.audioUnit!))
    var frames = 0; var peak: Float = 0
    input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { b, _ in
        frames += Int(b.frameLength); if let ch = b.floatChannelData { for i in 0..<Int(b.frameLength) { peak = max(peak, abs(ch[0][i])) } } }
    engine.prepare()
    do { try engine.start(); print("started on", auDevice(input.audioUnit!), "fmt", input.outputFormat(forBus: 0).sampleRate, input.outputFormat(forBus: 0).channelCount) } catch { print("start FAILED", error); exit(0) }
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/say"); p.arguments = ["-a", "\(spk.0)", "testing one two three"]; try? p.run()
    for s in 1...5 { Thread.sleep(forTimeInterval: 0.5); print(String(format: "t=%.1f frames=%d peak=%.4f", Double(s) * 0.5, frames, peak)); peak = 0 }
    engine.stop(); exit(0)
}

// --- raw AUVoiceIO ---
let target: AudioDeviceID = variant == "raw_agg" ? agg : variant == "raw_mic" ? mic.0 : variant == "raw_spk" ? spk.0 : 0
var cd = AudioComponentDescription(componentType: kAudioUnitType_Output, componentSubType: kAudioUnitSubType_VoiceProcessingIO, componentManufacturer: kAudioUnitManufacturer_Apple, componentFlags: 0, componentFlagsMask: 0)
let comp = AudioComponentFindNext(nil, &cd)!
var auOpt: AudioUnit? = nil
print("new:", AudioComponentInstanceNew(comp, &auOpt)); let au = auOpt!
var one: UInt32 = 1
print("enable input:", AudioUnitSetProperty(au, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Input, 1, &one, 4))
print("enable output:", AudioUnitSetProperty(au, kAudioOutputUnitProperty_EnableIO, kAudioUnitScope_Output, 0, &one, 4))
if target != 0 { print("pin \(target):", pin(au, target)) }
print("device:", auDevice(au))
var frames = 0; var peak: Float = 0
var fmt = AudioStreamBasicDescription()
var fsize = UInt32(MemoryLayout<AudioStreamBasicDescription>.size)
// input side (element 1, output scope = what we read)
print("get in fmt:", AudioUnitGetProperty(au, kAudioUnitProperty_StreamFormat, kAudioUnitScope_Output, 1, &fmt, &fsize), "rate", fmt.mSampleRate, "ch", fmt.mChannelsPerFrame, "flags", fmt.mFormatFlags, "bpf", fmt.mBytesPerFrame)
final class Ctx { var au: AudioUnit; var fmt: AudioStreamBasicDescription; init(_ a: AudioUnit, _ f: AudioStreamBasicDescription) { au = a; fmt = f } }
let ctx = Ctx(au, fmt)
var cb = AURenderCallbackStruct(inputProc: { (ref, flags, ts, bus, n, _) -> OSStatus in
    let c = Unmanaged<Ctx>.fromOpaque(ref).takeUnretainedValue()
    let nonInterleaved = (c.fmt.mFormatFlags & kAudioFormatFlagIsNonInterleaved) != 0
    let chans = nonInterleaved ? Int(c.fmt.mChannelsPerFrame) : 1
    let abl = AudioBufferList.allocate(maximumBuffers: chans)
    for i in 0..<chans { abl[i] = AudioBuffer(mNumberChannels: nonInterleaved ? 1 : c.fmt.mChannelsPerFrame, mDataByteSize: n * c.fmt.mBytesPerFrame, mData: nil) }
    let st = AudioUnitRender(c.au, flags, ts, 1, n, abl.unsafeMutablePointer)
    if st == noErr, let d = abl[0].mData?.assumingMemoryBound(to: Float.self) {
        frames += Int(n); for i in 0..<Int(n) { peak = max(peak, abs(d[i])) }
    } else if frames == 0 { print("render st", st) }
    abl.unsafeMutablePointer.deallocate()
    return noErr
}, inputProcRefCon: Unmanaged.passUnretained(ctx).toOpaque())
print("set input cb:", AudioUnitSetProperty(au, kAudioOutputUnitProperty_SetInputCallback, kAudioUnitScope_Global, 1, &cb, UInt32(MemoryLayout<AURenderCallbackStruct>.size)))
// output side: render silence
var ocb = AURenderCallbackStruct(inputProc: { (_, flags, _, _, n, abl) -> OSStatus in
    if let abl = abl { let p = UnsafeMutableAudioBufferListPointer(abl); for b in p { memset(b.mData, 0, Int(b.mDataByteSize)) } }
    flags.pointee = .unitRenderAction_OutputIsSilence; return noErr
}, inputProcRefCon: nil)
print("set render cb:", AudioUnitSetProperty(au, kAudioUnitProperty_SetRenderCallback, kAudioUnitScope_Input, 0, &ocb, UInt32(MemoryLayout<AURenderCallbackStruct>.size)))
let ist = AudioUnitInitialize(au); print("initialize:", ist)
if ist == noErr {
    print("start:", AudioOutputUnitStart(au), "device now", auDevice(au))
    let p = Process(); p.executableURL = URL(fileURLWithPath: "/usr/bin/say"); p.arguments = ["-a", "\(spk.0)", "testing one two three"]; try? p.run()
    for s in 1...5 { Thread.sleep(forTimeInterval: 0.5); print(String(format: "t=%.1f frames=%d peak=%.4f", Double(s) * 0.5, frames, peak)); peak = 0 }
    AudioOutputUnitStop(au)
}
AudioUnitUninitialize(au); AudioComponentInstanceDispose(au)
