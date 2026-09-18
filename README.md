# Brandeis Handshake RSS Simplifier

This package automatically converts Handshake public feed `9311` into a simpler RSS feed containing:

- Job title
- Employer
- Location, when explicitly available
- Expiration date
- A link to the original Handshake posting

GitHub checks the Handshake feed hourly and republishes the simplified version only when something changes.

## Set up in GitHub

1. Create a new public GitHub repository named `handshake-rss`.
2. Upload all files and folders from this package. Be sure to include the `.github` folder.
3. In the repository, open **Settings > Secrets and variables > Actions**.
4. Select **New repository secret**.
5. Enter `HANDSHAKE_FEED_URL` as the secret name.
6. Paste the complete Handshake RSS URL supplied for feed `9311` as the value, including its token.
7. Open **Actions > Update Handshake RSS > Run workflow > Run workflow**.
8. After the workflow finishes, open **Settings > Pages**.
9. Under **Build and deployment**, select **Deploy from a branch**, choose `main`, choose `/docs`, and save.

The simplified feed will normally be available at:

`https://YOUR-GITHUB-USERNAME.github.io/handshake-rss/handshake-feed-cleaned.rss`

Replace `YOUR-GITHUB-USERNAME` if needed. If the repository has a different name, replace `handshake-rss` too.

## Security

Keep the complete Handshake URL only in the GitHub secret. The token should not be pasted into the repository, README, Python file, or generated feed. The updater removes the source element that could otherwise reveal it.

Anyone with the final GitHub Pages URL can read the simplified job feed. They cannot see the original Handshake feed URL or token.

## Check that it is working

The first workflow run should create or refresh `docs/handshake-feed-cleaned.rss`. Opening the GitHub Pages URL should then display or download the simplified RSS XML.

If the Action fails with `Missing HANDSHAKE_FEED_URL secret`, confirm that the secret name is spelled exactly as shown above.

## Location limitation

Handshake does not provide location as a consistent dedicated RSS field. The script uses only location information explicitly present in the title or description. If it cannot identify a location safely, the output says `Not specified in RSS feed`.
