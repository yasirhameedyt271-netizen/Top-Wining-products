name: Auto-update GulfWinners data

on:
  schedule:
    - cron: "0 */6 * * *" # every 6 hours (UTC)
  workflow_dispatch: # lets you run it manually from the Actions tab

permissions:
  contents: write # needed to commit the updated files

concurrency:
  group: update-winners
  cancel-in-progress: false

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install dependencies
        run: pip install pandas numpy requests pillow

      - name: Rank winners and download images
        run: |
          python \
            --input-dir raw \
            --out-dir . \
            --download-images \
            --image-base-url "https://${{ github.repository_owner }}.github.io/${{ github.event.repository.name }}/"

      - name: Commit updated data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add gulf_top_100_winners.json gulf_top_100_winners.csv images
          if git diff --staged --quiet; then
            echo "No changes to commit"
          else
            git commit -m "Auto-update winners $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            git push
          fi
