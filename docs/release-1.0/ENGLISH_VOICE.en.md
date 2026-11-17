# English action voice — tiny-voca F2

Matching pair: Nyra 1.0.8 / 108, standalone and embedded in TWOS 1.0.11 / 101.59. Publication and actual playback validation are recorded separately in the final release receipt.

Chinese remains the same 13 Tian / Xiaotian 1413 recordings. English now defaults to 13 offline recordings generated with tiny-voca F2 (American English), matching the same actions: greeting, rest, work, confirmation, celebration, encouragement, outfit, wave, idle, reading, movement, jump and settling.

Open Sound, choose English, and select **tiny-voca F2 · English (US) · bundled cues**. Unmute to preview a cue; enable Action voice for eligible action transitions. Existing explicitly selected system voices and imported action recordings remain available; imported audio takes priority. Hide, mute and Stop immediately stop playback. Cooldown and truthful task completion rules are unchanged. Switching language never uses Chinese audio as an English fallback. A missing or damaged bundled recording is reported explicitly.

Generation happens during development using the public pinned ONNX weights. The app ships approximately 1.6 MB of WAV recordings, not a model, inference runtime, download service or subscription. It reads no task text aloud and sends no conversation content to a speech provider. No additional microphone, network or model permission is needed. F2 is a synthetic voice; its name is not an exclusive or cloned Nyra voice claim.

Sources: [tiny-voca](https://github.com/n4ze3m/tiny-voca), [model and voice limitations](https://huggingface.co/n4ze3m/tiny-voca). Code and model are Apache-2.0; the bundled pack preserves the upstream license and phonemizer notices. The manifest records the exact model revision/hash, voice, speed 0.95, original pitch, 24 kHz mono PCM, and per-cue SHA-256. Signal validation is separate from listening quality and Owner acceptance. Regeneration materials are documented in `docs/voice-generation/README.md` in the Nyra source.
