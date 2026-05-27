# Codex GitHub Sync Instructions v0.1

## Repository

```text
https://github.com/loseyourself1978-blip/tianma-work-os
```

## Recommended Local Path

```text
~/Projects/tianma-work-os
```

## Codex Task Prompt

```text
You are working on the GitHub repository:

https://github.com/loseyourself1978-blip/tianma-work-os

Task:
Create and organize the initial Tianma Work OS documentation repository.

Important:
- Do not upload private account screenshots, brokerage data, Binance screenshots, API keys, passwords, tokens, or private financial details.
- LLM Daredevil Desk should only be included as a sanitized public case study and cockpit specification.
- Use English only in GitHub documents.
- Preserve the product thesis: "You own the strategy. AI handles the execution."
- Commit message: "Add Tianma Work OS product blueprint documents"

Steps:
1. If the repo is not cloned locally, clone it.
2. Create the directory structure.
3. Copy the Markdown files from the upload package into the repo.
4. Run git status.
5. Run git add .
6. Commit with: git commit -m "Add Tianma Work OS product blueprint documents"
7. Push to GitHub.
8. Report final git status and repository URL.
```

## Shell Commands

```bash
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/loseyourself1978-blip/tianma-work-os.git
cd tianma-work-os
mkdir -p examples/llm-daredevil-desk templates
git status
git add .
git commit -m "Add Tianma Work OS product blueprint documents"
git push
```
