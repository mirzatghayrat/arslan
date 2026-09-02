import CoreAudio
import Foundation
func set(_ sel: AudioObjectPropertySelector, _ id: AudioDeviceID) -> OSStatus {
    var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var v = id; return AudioObjectSetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, UInt32(MemoryLayout<AudioDeviceID>.size), &v)
}
func get(_ sel: AudioObjectPropertySelector) -> AudioDeviceID {
    var addr = AudioObjectPropertyAddress(mSelector: sel, mScope: kAudioObjectPropertyScopeGlobal, mElement: kAudioObjectPropertyElementMain)
    var id: AudioDeviceID = 0; var size = UInt32(MemoryLayout<AudioDeviceID>.size)
    AudioObjectGetPropertyData(AudioObjectID(kAudioObjectSystemObject), &addr, 0, nil, &size, &id); return id
}
let a = CommandLine.arguments
if a.count == 3, let i = UInt32(a[1]), let o = UInt32(a[2]) { print("set in:", set(kAudioHardwarePropertyDefaultInputDevice, i), "out:", set(kAudioHardwarePropertyDefaultOutputDevice, o)) }
print("defaults now in=\(get(kAudioHardwarePropertyDefaultInputDevice)) out=\(get(kAudioHardwarePropertyDefaultOutputDevice))")
