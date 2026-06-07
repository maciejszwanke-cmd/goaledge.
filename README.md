
# GoalEdge - Football Predictions System

## Quick Start
1. Create a new GitHub repository named `goaledge`.
2. Upload all files from this folder to the repo.
3. Enable GitHub Pages:
   - Settings > Pages > Source: "Deploy from a branch"
   - Branch: main, Root
   - Save
4. Your frontend URL: `https://<username>.github.io/goaledge/index.html`

## Deploy Backend
1. Go to https://render.com and sign up.
2. Create a new "Web Service".
3. Connect your GitHub repository.
4. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python backend.py`
   - Environment: Python 3.12
5. Save and deploy.
6. Render URL: `https://<service-name>.onrender.com`

## Connect Frontend to Backend
1. Open `index.html` in the repo.
2. Find `const API_URL = 'TU_WKLEJ_URL_DO_BACKENDU';`
3. Replace with: `const API_URL = 'https://<service-name>.onrender.com';`
4. Save and commit.

## Test
- Open frontend URL on any device.
- Select a date and league.
- You should see matches with predictions.

## Notes
- Render free tier may sleep after inactivity.
- For production, consider upgrading Render plan.
