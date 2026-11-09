# Credits

FreedomOS exists thanks to a lot of people. Thank you all. 🙏

## Made by

- **[MatsuYoda-88](https://github.com/MatsuYoda-88)** - the idea, the design, every feature request and hours of hands-on testing on real PCs.
- **Claude** by [Anthropic](https://www.anthropic.com) - wrote the code with him, session by session.

## The brain

- **[llama.cpp](https://github.com/ggml-org/llama.cpp)** by Georgi Gerganov and the ggml-org contributors (MIT) - runs every brain. FreedomOS downloads the official builds from their GitHub releases.
- The brain models (each has its own license - check its page before using it for anything serious):

| In FreedomOS | Model page | Made by |
|---|---|---|
| Small 9B | [mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF](https://huggingface.co/mradermacher/DeepSeek-V4-Pro-Qwen3.5-9B-UNCENSORED-heretic-GGUF) | GGUF files by mradermacher, built on Qwen3.5 by the Qwen team; see the page for the fine-tune's authors |
| Big 35B | [unsloth/Qwen3.6-35B-A3B-GGUF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) | Qwen team (Alibaba Cloud); GGUF files by Unsloth |
| Bonsai 27B | [prism-ml/Ternary-Bonsai-2-27B-gguf](https://huggingface.co/prism-ml/Ternary-Bonsai-2-27B-gguf) | PrismML |
| Arete 27B | [bartowski/NousResearch_Arete-27B-GGUF](https://huggingface.co/bartowski/NousResearch_Arete-27B-GGUF) | Nous Research; GGUF files by bartowski |

## Pictures

- **[FLUX.2 klein](https://huggingface.co/black-forest-labs/FLUX.2-klein-4B)** by Black Forest Labs.
- **[Z-Image Turbo](https://huggingface.co/Tongyi-MAI/Z-Image-Turbo)** by Tongyi-MAI.
- **[stable-diffusion.cpp](https://github.com/leejet/stable-diffusion.cpp)** by leejet - runs Pixel Shop Lite without NVIDIA.
- GGUF picture + text-encoder files by **[Unsloth](https://huggingface.co/unsloth)**, and the FLUX.2 VAE files from **[Comfy-Org](https://huggingface.co/Comfy-Org)**.
- **[PyTorch](https://pytorch.org)**, and Hugging Face's **[diffusers](https://github.com/huggingface/diffusers)**, **[transformers](https://github.com/huggingface/transformers)**, **[accelerate](https://github.com/huggingface/accelerate)**, **[peft](https://github.com/huggingface/peft)**, **[safetensors](https://github.com/huggingface/safetensors)** and **[huggingface_hub](https://github.com/huggingface/huggingface_hub)**.
- **[bitsandbytes](https://github.com/bitsandbytes-foundation/bitsandbytes)** - squeezes the big picture model onto a 12 GB card.

## The app

- **[Microsoft Edge WebView2](https://developer.microsoft.com/microsoft-edge/webview2/)**, **.NET 8** and **Windows Forms** by Microsoft - WiBro and the whole FreedomOS window.
- **[winget](https://github.com/microsoft/winget-cli)** by Microsoft - installs Python, Tailscale and friends during setup.
- **[Python](https://www.python.org)** and these Python libraries:
  [aiohttp](https://github.com/aio-libs/aiohttp) · [Pillow](https://github.com/python-pillow/Pillow) · [pystray](https://github.com/moses-palmer/pystray) ·
  [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) · [Flask](https://github.com/pallets/flask) · [Waitress](https://github.com/Pylons/waitress) ·
  [sentencepiece](https://github.com/google/sentencepiece) · [tqdm](https://github.com/tqdm/tqdm)
- **[Inno Setup](https://jrsoftware.org/isinfo.php)** by Jordan Russell and Martijn Laan - the Windows installer.
- **[Steven Black's hosts list](https://github.com/StevenBlack/hosts)** - WiBro's ad + tracker blocker.
- **[LRCLIB](https://lrclib.net)** - the free synced lyrics behind WiMix karaoke.
- **[DuckDuckGo](https://duckduckgo.com)** and **[Bing](https://www.bing.com)** - Quick Ask and web search results.
- The live wallpapers come from MatsuYoda-88's own **web.walls** collection.

## Services FreedomOS works with

- **[Tailscale](https://tailscale.com)** - the private network for your phone, other PCs and friends.
- **[Claude Code](https://www.anthropic.com/claude-code)** and the **Claude desktop app** by Anthropic - the 💬 Claude chat and the crew plug-in (Model Context Protocol).
- **[YouTube Music](https://music.youtube.com)** (WiMix) and **[Discord](https://discord.com)** - FreedomOS just opens their own websites in a tab; you sign in with your own accounts.

## Built with GitHub Actions

[actions/checkout](https://github.com/actions/checkout) · [actions/setup-dotnet](https://github.com/actions/setup-dotnet) · [actions/setup-python](https://github.com/actions/setup-python) ·
[actions/upload-artifact](https://github.com/actions/upload-artifact) · [softprops/action-gh-release](https://github.com/softprops/action-gh-release)

---

YouTube, YouTube Music, Discord, Tailscale, Claude, Windows, Edge and every other product name here belong to their owners.
FreedomOS is a fan-made project and isn't made by, or endorsed by, any of them.
