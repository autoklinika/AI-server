Stage 27 sources:
- hermes_video_dispatch_stage27.py: deterministic worker wrapper
- qwen_prompt_compiler.py: local-only Qwen prompt compiler
- hermes_video_dispatch.py: unchanged Stage 26 transport base

Fallback contract: if Qwen is bypassed, Telegram warning must be delivered before LTX starts.
