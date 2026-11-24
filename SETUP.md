# Setup guide: put the Lore Shorts robot on GitHub

You do this once. About **75 minutes**, no coding. Each step ends with a
**Done when** line, so you know it worked before moving on.

When it is finished, this happens on its own:

1. The weekly script skill puts `spec.json` into a Drive folder such as
   `Lore Shorts/W1-1/`.
2. Within an hour the robot fetches the artwork and stock clips into
   `W1-1/assets/` and sends you a Telegram message.
3. You do the lore check, record the voice-over and upload it as `W1-1.m4a`
   into the same folder.
4. Within about 30 minutes (plus 5 to 15 minutes of cutting) the finished video
   arrives in Telegram, followed by the caption text for each platform.
5. You post it yourself. **The robot never posts anything.**

> **Keys and passwords: the golden rule.** You type every key into GitHub
> yourself. Never paste a key into a chat (including with Claude), an email, a
> document or a file in the repo. GitHub "secrets" are locked: once saved,
> nobody can read them, not even you, and they stay hidden on a public repo.

---

## Step 1. Make the GitHub repository (10 min)

1. Go to <https://github.com> and sign in (or click **Sign up**, it's free).
2. Click the **+** at the top right, then **New repository**.
3. **Repository name:** `lore-shorts-engine`
4. Choose **Public** or **Private**:

   | | Public (recommended) | Private |
   |---|---|---|
   | Robot running cost | Free, no limit | 2,000 free minutes a month. The default schedules use about 2,200, so you must slow them (see "Private repo" below) |
   | Who can see the code | Anyone (a nice portfolio piece) | Only you |
   | Your keys | Hidden either way | Hidden either way |
   | Catch | Schedules pause after 60 days with no changes. The included keep-alive job prevents this | None |

5. Leave "Add a README" and everything else **unticked**. Click
   **Create repository**.

Now put the files in. Pick **1A** or **1B**.

### 1A. Upload by drag and drop (works for everyone)

1. Unzip `lore-shorts-engine-release.zip` on your computer.
2. **Mac:** open the unzipped folder in Finder and press **Cmd + Shift + .**
   (full stop) so the hidden `.github` folder and `.gitignore` file appear.
   **Windows:** they are already visible.
3. On the new repo page, click the link **uploading an existing file**.
4. Select **everything inside** the unzipped folder (`.github`, `engine`,
   `pipeline`, `tests`, `fonts`, `assets`, `samples`, `specs`, and all the
   files) and drag it onto the page. Use Chrome or Edge, which keep folders
   intact.
5. Wait until the file list finishes loading, then click **Commit changes**.

**Done when:** the repo page shows a `.github` folder, and inside it
`workflows` with `cut.yml`, `gather.yml` and `keepalive.yml`.
(If `.github` is missing, the hidden-files step was skipped. Repeat 1A.2 to
1A.5 with only the `.github` folder.)

### 1B. Or let Claude upload it for you

1. In claude.ai open **Settings**, then **Connectors**. Find **GitHub**, click
   **Connect** and allow access to the `lore-shorts-engine` repository (the
   names of these menus may differ slightly).
2. In a chat, ask Claude to push the lore shorts engine to your repo.

**Done when:** you see the same as in 1A.

---

## Step 2. Copy two IDs from Google (3 min)

Open a note on your computer and paste these two IDs. They are not secret, but
you'll need them in Step 7.

* **Drive folder ID.** Open the **Lore Shorts** folder in Google Drive. The
  address looks like `https://drive.google.com/drive/folders/1AbC...xyz`.
  Everything after `folders/` (and before any `?`) is the folder ID.
* **Tracker sheet ID.** Open the **Lore Shorts Tracker** sheet. The address
  looks like `https://docs.google.com/spreadsheets/d/1MGl...dU/edit`.
  The long part between `/d/` and `/edit` is the sheet ID.

**Done when:** both IDs are in your note.

---

## Step 3. Make a Google Cloud project (10 min)

1. Go to <https://console.cloud.google.com> and sign in with the **same Google
   account that owns the Lore Shorts folder**. Accept the terms if asked. No
   payment card is needed for this.
2. At the top left, click the project picker (it may say "Select a project"),
   then **New project**. Name it `lore-shorts`, click **Create**, then select
   it in the project picker.
3. In the search bar at the top, type **Google Drive API**, open it, and click
   **Enable**.
4. Search for **Google Sheets API**, open it, and click **Enable**.

**Done when:** both APIs show "API enabled" (or a **Manage** button).

---

## Step 4. Give the robot access to Google (10 to 15 min)

First, check where the **Lore Shorts** folder lives:

* In **My Drive** on a normal `@gmail.com` account (most likely): do **4A**.
  Google does not let a "service account" robot save new files into a normal
  My Drive, so the robot needs to act as you.
* In a **Shared drive** (Google Workspace): you can do **4B** instead.

You only need **one** of these.

### How to add a GitHub secret (you'll do this several times)

In your repo, click **Settings** (the top tab), then in the left menu click
**Secrets and variables**, then **Actions**. On the **Secrets** tab click
**New repository secret**. Type the **Name** exactly as written here (capital
letters, underscores), paste the value into **Secret**, and click
**Add secret**.

### 4A. Let the robot act as your Google account (15 min)

1. In Google Cloud (your `lore-shorts` project), search for
   **Google Auth Platform** (older screens call it **OAuth consent screen**)
   and click **Get started**.
   * App name: `Lore Shorts Robot`. User support email: your email.
   * Audience: **External**.
   * Contact email: your email. Agree, then click **Create**.
2. In the left menu click **Audience**, then **Publish app**, then
   **Confirm**. (While an app is in "Testing", Google logs the robot out
   every 7 days. Publishing stops that. Nobody else can use the app.)
3. In the left menu click **Clients**, then **+ Create client**.
   * Application type: **Web application**. Name: `Lore Shorts Robot`.
   * Under **Authorized redirect URIs** click **+ Add URI** and paste
     `https://developers.google.com/oauthplayground`
   * Click **Create**. A box shows a **Client ID** and a **Client secret**.
     Keep this tab open.
4. In a new tab open <https://developers.google.com/oauthplayground>.
   Click the **gear icon** (top right), tick **Use your own OAuth
   credentials**, and paste the Client ID and Client secret. Close the gear
   box.
5. On the left, in the box **Input your own scopes**, paste exactly:
   `https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/spreadsheets`
   then click **Authorize APIs**.
6. Choose your Google account. You will see "Google hasn't verified this
   app". That's expected, because it's your own app. Click **Advanced**, then
   **Go to Lore Shorts Robot (unsafe)**, tick the boxes, and click
   **Continue**.
7. Back in the Playground, click **Exchange authorization code for tokens**.
   Copy the value next to **Refresh token**.
8. Add three GitHub secrets (see "How to add a GitHub secret" above):

   | Name | Value |
   |---|---|
   | `GOOGLE_OAUTH_CLIENT_ID` | the Client ID from 3 |
   | `GOOGLE_OAUTH_CLIENT_SECRET` | the Client secret from 3 |
   | `GOOGLE_OAUTH_REFRESH_TOKEN` | the Refresh token from 7 |

9. Close the Playground tab.

**Done when:** the three secrets are listed under Repository secrets.
(If the robot later says `invalid_grant`, redo 4A.4 to 4A.8 and replace
`GOOGLE_OAUTH_REFRESH_TOKEN`.)

### 4B. Or use a service account (only for a Shared drive, 10 min)

1. In Google Cloud, search for **Service Accounts** and open it. Click
   **+ Create service account**, name it `lore-shorts-robot`, click
   **Create and continue**, skip the optional roles (**Continue**), and click
   **Done**.
2. Click the new account, open the **Keys** tab, then **Add key**, then
   **Create new key**, then **JSON**, then **Create**. A `.json` file
   downloads.
3. Open that file in Notepad (Windows) or TextEdit (Mac). Select all and copy.
   Add a GitHub secret named `GOOGLE_SERVICE_ACCOUNT_JSON` and paste the whole
   text, from the first `{` to the last `}`.
4. **Delete the downloaded file** and empty the bin. GitHub now holds the only
   copy you need.
5. Copy the service account's email (it ends in `.iam.gserviceaccount.com`).
   * In Drive, right-click the **Lore Shorts** folder (or the Shared drive),
     click **Share**, paste the email, choose **Editor**, untick **Notify**,
     and click **Share**.
   * In the **Lore Shorts Tracker** sheet, click **Share**, paste the email,
     choose **Editor**, and click **Send**.

**Done when:** the secret is saved and both shares show the robot's email as
Editor. (If Google says key creation is disabled, your Workspace admin
blocks it. Use 4A.)

---

## Step 5. Pexels key for stock clips (5 min)

1. Go to <https://www.pexels.com/join> and sign up (free).
2. Go to <https://www.pexels.com/api> and click **Your API Key** (or
   **Get started**). Fill in the short form, for example "Personal project:
   automatic search for stock footage for my own YouTube Shorts", and
   submit.
3. Copy the key and add a GitHub secret named `PEXELS_API_KEY`.

**Done when:** `PEXELS_API_KEY` is listed under Repository secrets.

---

## Step 6. Telegram bot for the finished videos (10 min)

1. In Telegram, search for **@BotFather** (it has a blue tick) and open it.
2. Send `/newbot`. Give it a name (e.g. `Lore Shorts`) and then a username
   that ends in `bot` (e.g. `rishabh_lore_shorts_bot`).
3. BotFather replies with a **token** like `123456789:AAH...`. Add a GitHub
   secret named `TELEGRAM_BOT_TOKEN` with that token.
4. Tap the link to your new bot, press **Start**, and send it any message,
   e.g. `hi`.
5. On your own computer, open this address in your browser, replacing
   `<TOKEN>` with your token:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Find `"chat":{"id":` followed by a number, e.g. `"chat":{"id":123456789`.
   That number is your chat ID. (This page shows your token in the address
   bar, so don't screenshot or share it.)
6. Add a GitHub secret named `TELEGRAM_CHAT_ID` with that number.

**Done when:** both Telegram secrets are listed. (If the page in 5 shows
`"result":[]`, send the bot another message and reload.)

---

## Step 7. Tell the robot where your files are (5 min)

In your repo, click **Settings**, then **Secrets and variables**, then
**Actions**. This time open the **Variables** tab and click **New repository
variable** twice:

| Name | Value |
|---|---|
| `TRACKER_SHEET_ID` | the sheet ID from Step 2 |
| `DRIVE_ROOT_FOLDER_ID` | the Drive folder ID from Step 2 |

**Done when:** you have 2 variables, plus these secrets:

* If you did 4A, 6 secrets: `GOOGLE_OAUTH_CLIENT_ID`,
  `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REFRESH_TOKEN`,
  `PEXELS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
* If you did 4B, 4 secrets: `GOOGLE_SERVICE_ACCOUNT_JSON`, `PEXELS_API_KEY`,
  `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

---

## Step 8. First test run (15 min, plus about 15 min for the first cut)

1. Make sure Drive has a short folder with a spec in it, e.g.
   `Lore Shorts/W1-1/spec.json` (the weekly script skill makes these).
2. In your repo click the **Actions** tab. If GitHub asks, click
   **I understand my workflows, go ahead and enable them**.
3. On the left click **Gather visuals**, then **Run workflow** (on the right),
   then the green **Run workflow** button.
4. After about 10 seconds a run appears. Wait for it to finish (1 to 3 min).
   * **Green tick** means success. Click the run, then **gather**, then the
     **Gather** step, and you'll see lines like
     `[gather] W1-1: 7/9 lines filled`.
   * In Drive, `W1-1/assets/` now holds the pictures, clips,
     `licences.csv` and a `.done` file.
   * Telegram shows "W1-1: visuals gathered for 7 of 9 lines", plus the
     reason for each line it skipped.
5. Now record the voice-over and upload it to the `W1-1` folder with the
   name **`W1-1.m4a`** (`.mp3` or `.wav` also work). In the Drive phone app,
   tap the file's **⋮** and then **Rename** if your recorder named it
   something else.
6. Back in **Actions**, click **Cut shorts**, then **Run workflow**. The
   first cut takes about 10 to 20 minutes because it downloads the speech
   and depth models once. Later cuts take about 5 to 10.

**Done when:** Telegram shows the video, then one message per platform with
its caption text, and Drive has `W1-1.mp4` and `W1-1.qa.json`. The Post log
row says **Recorded** and its Notes say "Rendered <date>, QA passed".

If a run shows a **red X**, click it, open the red step, read the last lines,
and check the table below.

---

## When something goes wrong

| The log or Telegram says | Fix |
|---|---|
| `Missing setting DRIVE_ROOT_FOLDER_ID` (or `TRACKER_SHEET_ID`) | Step 7. Check the variable name is spelled exactly right |
| `No Google login found` | Step 4. Check the secret names |
| `service accounts cannot save files ... step 4A` | Your folder is in a normal My Drive. Do 4A (you can leave the 4B secret; 4A wins) |
| `invalid_grant` | Your Google login expired. Make sure the app is **published** (4A.2), then redo 4A.4 to 4A.8 |
| `File not found` / `404` | Wrong folder ID, or (4B) the folder isn't shared with the robot's email |
| `The caller does not have permission` / `403` on the sheet | Wrong sheet ID, or (4B) the sheet isn't shared with the robot |
| `Telegram sendMessage refused: chat not found` | Press **Start** in your bot's chat, then check `TELEGRAM_CHAT_ID` |
| `PEXELS_API_KEY is not set` or `401` | Step 5. Re-add the key |
| `spec.json is a Google Doc` | The spec must be a plain file called `spec.json`, not a Google Doc |
| Telegram: "the cut FAILED" | Read `<ID>.error.txt` in the Drive folder. After fixing, delete that file (or upload the voice again) and it retries |
| Schedules stopped running (public repo) | **Actions**, pick the workflow, then **Enable workflow** |

## Everyday use

* **The weekly rhythm:** the script skill puts each short's `spec.json` in its
  own folder and adds a Post log row with Status `Scripted`. Do your lore
  check in the week's script doc, then set the Status to `Checked`. Visuals
  are only collected after that, so nothing is downloaded for a script you
  then change. Record, drop the voice file in the short's folder, and the
  video lands in that folder as `W1-1.mp4`, with `W1-1.post.txt` beside it
  (QA result plus ready-to-copy titles and captions per platform). Telegram
  is optional: without its secrets, the pipeline just skips those messages.
* **Google login expired:** while the Google app is in Testing mode, the
  refresh token lasts 7 days. A run then fails with "Google login expired"
  and GitHub emails you. Redo the OAuth Playground part of step 4 (signed in
  as the channel account) and update the `GOOGLE_OAUTH_REFRESH_TOKEN` secret.
* **Redo the visuals for a short:** delete `assets/.done` (and any file you
  want replaced). The next hourly run fills in what's missing.
* **Use your own picture or clip for line 3:** put `03.jpg` (or `03.png` or
  `03.mp4`) into `assets/`, then delete `assets/.done`.
* **Re-record:** upload the new voice file with the same name. The newer file
  triggers a fresh cut.
* **Licences:** `assets/licences.csv` lists every picture and clip with its
  source. Rows with `credit_required = yes` need a credit line in your
  description (for example, "Image: NASA" or the artist with the CC licence).

## Private repo: slow the schedules down

Each run counts as at least 1 minute. Every 30 minutes plus hourly comes to
about 2,200 minutes a month, which is more than the free 2,000. On a private
repo, edit these two files on GitHub (open the file, then the **pencil icon**,
then **Commit changes**):

* `.github/workflows/cut.yml`: change `"13,43 * * * *"` to `"13 * * * *"`
  (hourly, about 720 min)
* `.github/workflows/gather.yml`: change `"7 * * * *"` to `"7 */3 * * *"`
  (every 3 hours, about 240 min)

Plus the real cutting time (about 10 min per short), you stay well under
2,000. To check usage, open your GitHub profile picture, then **Settings**,
then **Billing and licensing**.

## If a key ever leaks

* **Google (4A):** in Google Cloud, open **Clients**, click your client, and
  reset its secret. Then redo 4A.4 to 4A.8.
* **Google (4B):** in **Service Accounts**, open your account, go to
  **Keys**, and delete the key. Then make a new one.
* **Telegram:** send `/revoke` to @BotFather, then save the new token.
* **Pexels:** sign in to the Pexels API page and request a new key.

Then update the GitHub secret with the new value.
