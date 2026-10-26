# Deploying the demo (Streamlit Community Cloud)

The hosted demo runs in **local-data mode**: no Snowflake and no AI key. On first load it builds the seeded synthetic dataset
and the model outputs (about 20 seconds), then caches them. Everything shown is synthetic.

## Steps

1. Merge the deploy-ready changes into `main` on GitHub.
2. Go to https://share.streamlit.io, sign in with GitHub, and choose **Create app -> Deploy a public app from GitHub**.
3. Settings:
   - Repository: `ragurajakrishnan15/Cloud_Spend`, branch `main`
   - Main file path: `app/Home.py`
   - **Advanced settings -> Python version: 3.11** (the pinned dependencies were tested on 3.11)
   - Leave **Secrets empty**.
4. Deploy. The first start installs dependencies (a few minutes). Share the `https://<name>.streamlit.app` URL.

## Keep these out of the hosted app

- **Do not add Snowflake credentials or `LLM_API_KEY` as secrets** on a public app. A public link would let anyone use your
  warehouse credits or exhaust your AI quota. With no secrets the app uses local data and deterministic answers.
- `.env` is git-ignored and is never part of the deployment.

## Notes

- Streamlit Community Cloud apps go to sleep after a period of inactivity; the first visit after that takes a short while to
  wake the app and rebuild the cached data.
- To also show the AI wording layer publicly, use a separate key with a small quota and a spending cap, and accept that
  visitors can trigger calls with it. This is not recommended for a recruiter-facing link.
