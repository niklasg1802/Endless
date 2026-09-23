# 0002 – MiniMax H3 as the primary video model

**Context:** In the proof of concept (#1, #3) we tried MiniMax H3 (cloud, via OpenRouter) and Veo 3.1 Lite on the
same Rick and Morty scene. The humans rated H3's voices and video "far better". But H3's cloud moderation blocks
show and character names in text, and it recognises the characters in reference and first-frame images.

**Decision:** MiniMax H3 is the primary video model. Shots with accurate character designs run on **local H3** on
the 3090 Ti rig: open weights, run through ComfyUI, using int8 or GGUF files. Cloud H3 and other cloud models are
only fallbacks, for prompts that don't name the show.

**Consequences:** Getting the rig working (#6, #7) is on the critical path. Cloud prompts must never name the show
or its characters. Keyframes are made with an image model first and then animated.
