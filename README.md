# Instahyre Profile Refresh Automation

An automated, serverless pipeline running on **GitHub Actions** designed to refresh recruiter-facing timestamps on **Instahyre**, keeping candidate profiles continuously marked as **"Active Today"** without manual intervention.

---

## How It Works

* **Session & CSRF Management:** Authenticates via Instahyre's login API and captures runtime CSRF tokens.
* **Resume Timestamp Refresh:** Re-uploads the target resume payload to update the candidate resume modification timestamp.
* **Job Search Preferences (JSP) Touch:** Sends an automated update for candidate preferences to ensure the profile activity badge stays current.
* **Anti-Bot Jitter:** Employs randomized sleep intervals (1 to 15 minutes) during CI runs to avoid predictable clock-time patterns.
* **Real-time Alerting:** Dispatches instant execution metrics and failure logs directly to Telegram.

---

## Repository Structure

```text
├── .github/
│   └── workflows/
│       └── refresh.yml          # GitHub Actions scheduled workflow
├── helper.py                    # Base64 encoding & payload construction
├── main.py                      # Core execution script
├── requirements.txt             # Python dependencies
└── resume.pdf                   # Target resume file uploaded on each run



Setup Guide1. 
Configure GitHub Repository SecretsIn your GitHub repository, go to Settings → Secrets and variables → Actions and add the following secrets:Secret NameDescriptionSource / How to ObtainINSTAHYRE_EMAILInstahyre login emailYour registered account emailINSTAHYRE_PASSWORDInstahyre login passwordYour registered account passwordTELEGRAM_BOT_TOKENBot API tokenCreated via Telegram @BotFatherTELEGRAM_CHAT_IDNumeric Chat/User IDChecked via Telegram @userinfobot


2. Configure Resume AssetPlace your latest resume inside the repository root directory.Name the file exactly:Plaintextresume.pdf
(If you wish to use a different filename or path, update the RESUME_FILE variable in main.py).Commit and push resume.pdf to your repository branch.3. Execution ScheduleThe automation is configured in .github/workflows/refresh.yml:Scheduled Execution: Runs daily on GitHub Actions cron:YAMLschedule:
  - cron: "55 3 * * *"   # Triggers daily at 09:25 AM IST (03:55 AM UTC)
Randomized Jitter: An automated jitter delay (60–900 seconds) executes before the API calls to randomize the daily update minute.Manual Trigger: Run the workflow at any time by going to the Actions tab on GitHub, selecting Refresh Instahyre Resume, and clicking Run workflow.4. Telegram NotificationsAfter every scheduled or manual run, the script posts execution metrics to your Telegram bot.Success Alert Preview:Plaintext🚀 Instahyre Daily Refresh Completed

🟢 Status: Success
  • Resume: 2026-09-09 09:30:15
  • Profile: 2026-09-09 09:30:16

⚡ Time: 2.14s | 🕒 2026-09-09 09:30:18
Failure Alert Preview:Plaintext🔴 Instahyre Refresh Failed

Reason: Missing Instahyre credentials.
Local Development & TestingTo test the script on your local machine:Bash# 1. Install dependencies
pip install -r requirements.txt

# 2. Create a local .env file
cat <<EOF> .env
INSTAHYRE_EMAIL=your_email@example.com
INSTAHYRE_PASSWORD=your_password
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
SKIP_JITTER=true
EOF

# 3. Run the script
python main.py
DisclaimerThis project is built for personal job search management and automation. Ensure your usage adheres to Instahyre's Terms of Service.
