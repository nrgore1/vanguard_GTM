# Vanguard-GTM — Campaigns & Outreach Manual

Version 0.15.1 · updated 2026-10-03 · for everyone who runs partner campaigns at https://gtm.vireoka.com
See also the [User Guide](USER_GUIDE.md) for the rest of the app.

This manual takes you through a campaign from start to finish:

1. set the app up once (an admin does this);
2. get partners ready, with contacts and warm paths;
3. create a campaign and put partners in it;
4. run the outreach: approve and send emails, and send LinkedIn and X messages by hand;
5. track progress every day and every week.

Throughout, the example is the campaign you're running now: **LiqMint Institutional – Q4 design
partners**. It covers the 10 people you sent LinkedIn requests to on Oct 1, plus the partners with
published inboxes.

---

## 0. How the pieces fit

```
Partners ──(Add partners)──▶ Campaign ◀── counts automatically ──┐
   │                                                                  │
   ├── Outreach emails: draft ─▶ approved ─▶ sent ─▶ replied ────────┤
   ├── LinkedIn / X messages you send by hand, logged on the partner ─┤
   ├── Replies, calls, meetings, demos logged on the partner ─────────┤
   └── Stage: identified ─▶ contacted ─▶ in conversation ─▶ pilot ─▶ signed
```

- A **partner** is an organisation, such as Lead Bank. It holds the contact, the email sequence and
  the timeline of everything that happened.
- A **campaign** is a push with a goal and dates, such as "8 meetings by Dec 18". A partner sits in
  **one campaign at a time**.
- Once a partner is in a campaign, its emails sent, LinkedIn/X touches, replies, meetings and stage
  changes **count towards the campaign automatically**. You never type those numbers in.
- **Nothing is sent without an admin's approval.** LinkedIn and X messages are always sent by a
  person, by hand. The app never logs into LinkedIn.

| Who | Can do |
|---|---|
| Admin (Narendra) | Everything below, including **approving and sending emails** and passing readiness gates |
| User (team) | Create campaigns, add partners, edit drafts, log LinkedIn/X touches, calls and meetings, record replies, import their own LinkedIn connections. **Cannot approve or send email.** |

---

## 1. One-time setup (admin)

### 1.1 Deploy v0.9.0 on the server
In the Hostinger browser terminal (the prompt must read `liqmintadmin@srv1976317`):

```bash
cd /opt/vanguard-gtm
sudo git pull
sudo docker compose up -d --build
sudo docker exec vanguard-gtm vanguard db info
```

`db info` should say `PostgreSQL`. Then mark the 10 LinkedIn connection requests from Oct 1 as
LinkedIn touches. They were saved as plain notes before LinkedIn existed as a type:

```bash
sudo docker exec vanguard-gtm python -c "
from vanguard.web.db import WebStore; s=WebStore()
s.q(\"UPDATE partner_interactions SET type='linkedin' WHERE summary LIKE 'LinkedIn connection request sent to%'\")
print('done')"
```

### 1.2 Turn on real email
Until you do this, the app is in **outbox mode**: "sent" emails are only saved inside the app and
nothing is delivered. To send from your Hostinger mailbox, add these lines to
`/opt/vanguard-gtm/.env` (`sudo nano .env`):

```
VANGUARD_EMAIL_MODE=smtp
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=587
SMTP_USER=naren@atmakosh.com
SMTP_PASSWORD=<the mailbox password>
VANGUARD_SENDER_NAME=Narendra Gore
VANGUARD_SENDER_EMAIL=naren@atmakosh.com
VANGUARD_SENDER_ADDRESS=<your business postal address>
VANGUARD_EMAIL_DAILY_CAP=20
```

The variable names matter. They are `SMTP_HOST`, `SMTP_USER` and so on, **without** a `VANGUARD_`
prefix. The postal address is required by US anti-spam law (CAN-SPAM). The app won't send without
it, and it adds it to every email together with an opt-out line.

**Vireoka, LiqMint and LiqMint Institutional send from a vireoka.com address** (v0.13.0). Add a second
mailbox for them; everything not set here is taken from the lines above:

```
VANGUARD_MAILBOXES=vireoka
VANGUARD_MAILBOX_VIREOKA_PROPERTIES=vireoka,liqmint,liqmint-institutional
VANGUARD_MAILBOX_VIREOKA_SENDER_EMAIL=<your vireoka.com mailbox>
VANGUARD_MAILBOX_VIREOKA_SMTP_PASSWORD=<that mailbox's password>
```

Each mailbox has its own daily cap (20 unless you add `VANGUARD_MAILBOX_VIREOKA_DAILY_CAP`), and Check
replies reads both inboxes. Outreach shows both senders at the top; Write email shows which one a message
will come from.

**A copy in your Sent folder** (v0.13.1). SMTP doesn't keep a copy of what it sends, so the app saves one to
the mailbox's Sent folder using the IMAP lines below. Without those lines emails still go out, but you
won't see them in webmail's Sent folder; check the partner's timeline instead.

### 1.3 Reply detection (recommended)
Add these lines too, so the app can read replies from your inbox. With automatic sending on (§1.4),
the inbox is checked every tick. Without it, an admin clicks **Check replies** on Outreach.

```
IMAP_HOST=imap.hostinger.com
IMAP_USER=naren@atmakosh.com
IMAP_PASSWORD=<the mailbox password>
```

### 1.4 Automatic sending (needed for scheduled emails)
With this line, approved emails go out on their own as they fall due. Without it, they go out only
when an admin clicks **Send due now**.

```
VANGUARD_OUTREACH_EVERY_MIN=30
```

Use 10 if you schedule emails for specific times (§3.4), so they go within 10 minutes of their time.
Every 30 minutes, the app then sends what's due (only approved emails, within the daily cap) and,
if IMAP is set, checks for replies.

Apply the changes with `sudo docker compose up -d`.

**Check:** open **Outreach**. The banner at the top should read **"Live email … Approved messages
really send"** and **"Reply sync: IMAP on"**. If it lists a problem in red, such as a missing postal
address, fix that line in `.env` and restart.

### 1.5 Team accounts
**Admin → Users → Add user.** Team members get the **user** role. They can do the work, but they
can't approve or send email.

---

## 2. Get partners ready

### 2.1 Load the researched partners
**Partners → Load researched partners** (admin). This loads every organisation from the research
file, with its priority (P0/P1/P2), why it fits, the named people, the best route in and three
drafted emails. Running it again is safe: it refreshes and never duplicates.

### 2.2 Add contact emails, the only thing that blocks email
**Only a named person's own address** (v0.15.1). The app never emails a general inbox (support@, info@,
hello@, sales@, partnerships@, deals@ and the like): it refuses to save one, and anything queued to one is
cancelled. An address built from the contact's name (andrew.brackin@, abrackin@, brackin@ for Andrew Brackin) is
used as is. Any other address (a personal Gmail, a nickname) waits until you tick **This is <name>'s own
address** on the partner's Edit form or in Write email. If an organisation only publishes a general inbox, reach
the person on LinkedIn or X instead (§3.5b); the inbox stays visible under How to find.

An email can only go to a partner that has a contact email. To add one:

1. open the partner, then click **Edit**;
2. fill in **Contact email** (and **Contact name** if it's empty);
3. click **Save**.

Use only:
- an inbox the organisation publishes (for example hello@klaros.com);
- an address the person gave you, or that LinkedIn shared with you (see §4);
- a work address confirmed by an email-verification tool.

**Never guess an address** (firstname.lastname@…). Bounces damage your mailbox's reputation for
every later email.

The address is read when the email is sent, not when it's approved, so you can approve first and
add the address later.

### 2.3 Find warm paths
Import your LinkedIn connections (§4). The **Known** column on Partners then shows how many of the
team's connections work at each organisation. A warm introduction beats any cold message, so check this
column before anyone writes to a partner.

---

## 3. Create and run a campaign

### 3.1 Create the campaign
**Campaigns → New campaign.**

| Field | What to enter | Example |
|---|---|---|
| Name | Property, audience, quarter | LiqMint Institutional – Q4 design partners |
| Property | The property the partners belong to | LiqMint Institutional Edition |
| Type | `partner` for partner outreach; `social` for a LinkedIn-only push | partner |
| Channel | Free text | LinkedIn + email |
| Status | Start at `draft`; switch to `active` the day you start | active |
| Start date / End date | The push's dates | Oct 1 – Dec 18 |
| Goal metric + Goal value | One measurable number: meetings is best for partner work | Meetings, 8 |
| Budget (USD) | What you'll spend (usually $0 for partner work) | 0 |
| Owner | Who answers for the result (defaults to you) | Narendra |
| Description / audience | The offer and the one sentence the team should use | 6-week paid proof-of-value, read-only start… |

### 3.2 Add the partners
On the campaign page, click **Add partners**.

1. Search or scroll, and tick the partners. The list shows the campaign property's named
   partners; segments, declined partners and partners already in this campaign are left out.
2. Click **Add N**.

Things to know:
- A partner that's already in another campaign shows "in '…'". Ticking it **moves** it here.
- Attaching a whole segment from the command line brings in every named organisation under it.
- To take a partner out, click **×** on its row. Its history stays, but it stops counting here.

Command-line equivalent (admin, on the server):
```bash
sudo docker exec vanguard-gtm vanguard campaign list --property liqmint-institutional
sudo docker exec vanguard-gtm vanguard campaign attach 1 "Lead Bank" "Protiviti" "Crowe LLP"
```

### 3.3 Review and approve the emails (admin)
On the campaign page, click **Open in Outreach**. This opens the Outreach page filtered to this
campaign, on **Needs approval**.

1. Click a message to open it. Read it the way the recipient would. Change any line in the subject
   or body, then click **Save edits**. A saved message is checked again against the claim rules: no
   customer claims, no network-support claims, no yield language.
2. A message marked **claims: blocked** can't be approved until the copy is fixed.
3. Tick the messages that are ready, or **Select all**, then click **Approve**.

**Don't approve both channels for the same person in the same week.** If you have just reached
someone on LinkedIn, leave their email sequence unapproved until you know whether LinkedIn worked.
Otherwise they get the same pitch twice.

### 3.4 Send
**Schedule it** (v0.14.0). Any email can have a send date and time; it still needs approval, and it won't go
before that time:
- **One email:** in **Write email**, set **When** to "On a date and time". An admin's button then reads
  **Approve & schedule**. To change it later, open the email (Outreach, or the partner's page) and use
  **Schedule** or **Clear**.
- **A campaign's emails:** on **Outreach**, filter by the campaign, tick the emails (Needs approval, or
  Queued for an admin), click **Schedule**, and choose the start, how many per day, minutes apart, and
  weekdays only. For example 40 emails, 10 a day, 5 minutes apart from Tuesday 9:00 runs Tuesday to the
  following Monday, skipping the weekend.
- Times are in your time zone. Follow-up steps still wait for their delay after the previous email; a
  scheduled follow-up goes at whichever is later. The daily cap still applies.
- Scheduled emails go on time only when automatic sending is on (§1.4). Otherwise they go the first time an
  admin clicks **Send due now** after their time; the app warns you about this when you schedule.

- **Automatically**, if §1.4 is on: due messages go out at the next 30-minute tick.
- **By hand:** **Outreach → Send due now**. A report lists what was sent and why anything was held.

| Held because | What to do |
|---|---|
| no contact email on the partner yet | Add one (§2.2). It goes out on the next run. |
| waiting for step N to be sent / due {date} | Nothing. Step 2 waits until step 1 has gone out and its wait (usually 4 days) has passed. Step 3 waits about 9 days after step 2. |
| scheduled for {time} | Nothing: it goes at that time (with automatic sending on). Change it from the email's Schedule box. |
| daily cap of 20 reached | It goes tomorrow. Raise `VANGUARD_EMAIL_DAILY_CAP` only once replies show your mailbox is trusted. |
| partner already replied - sequence stopped | Correct: answer the reply yourself (§3.6). |
| address opted out / bounced - cancelled | Never email that address again. Use another route. |
| partner is declined - cancelled (or signed) | Correct: the deal is closed either way. |
| this is a segment - add named organisations under it, then approve their messages | Segments are templates. Add the real organisation under the segment and approve its copy. |

**One-off emails** (v0.12.0). Investors, and anyone you want to write to outside a sequence: open the partner
and click **Write email**. Fill in **To** (only an address the person or their firm published or shared with
you; it is saved as the contact email), the subject and the message. **Save draft** puts it in the approval
queue; an admin can click **Approve & send** to send just that one email at once. The claim rules apply as
usual, except that a sentence about our own raise ("We're raising a $3M seed") needs no source. A one-off
isn't stopped by a reply, so it is also how you answer one from the app. If the dialog says
**Email isn't connected yet**, do §1.2 first; until then it only saves to the outbox.

Each sent email automatically adds a dated **"Sent step N"** entry to the partner's timeline and
moves the partner from Identified to **Contacted**.

### 3.5 LinkedIn and X (sent by hand, logged in one click)
The app never sends LinkedIn or X messages for you. The person who sends one logs it:

1. Send the message in LinkedIn or X as yourself. The tailored follow-up for each of your 10 Oct 1
   contacts is saved as a note on their partner page.
2. On the partner page, under **Log an interaction**:
   - **Type:** LinkedIn (or X);
   - **What happened:** for example "Connection request sent with note" or "Follow-up message sent after accept";
   - **Move stage to:** Contacted, the first time;
   - **Next step:** what happens next and by when.
3. Click **Log interaction**. It counts straight away as a **LinkedIn/X touch** on the campaign.

To spot accepted requests without checking LinkedIn person by person, re-import your connections
every week (§4). When a partner's named contact (its Contact name) appears in your export, the
partner gets a **"Connected on LinkedIn"** entry.

### 3.5b LinkedIn and X sequences (v0.15.0)
Any partner's 3-step sequence (first message, follow-up, final nudge) can run on LinkedIn or X instead of email:

1. **Edit** the partner and add their **LinkedIn profile** link or **X handle**. A LinkedIn import fills the
   profile for named contacts who are already connections.
2. On the partner page, in **Outreach sequence**, pick **LinkedIn** or **X**. Unsent steps move to that channel
   and go back to **Needs approval**. Keep step 1 under 200 characters on LinkedIn if you aren't connected:
   it goes as the connection-request note (the app warns you).
3. An admin approves the steps as usual; schedule them if you like (§3.4).
4. When a step is due it shows on **Outreach → By hand** as **due now**. Click **Send on LinkedIn/X**: copy the
   message, **Open profile**, send it there (Connect → Add a note for a first LinkedIn step if not connected,
   otherwise Message), then click **I sent it**. That logs the touch, moves the partner to Contacted, and
   starts the wait before the next step.
5. When they reply, use **Record reply** with the channel. The remaining steps stop.

The app never posts on LinkedIn or X for you (no automation, no scraping), which keeps your accounts safe.
For a single message, **Write email** has a **Channel** option for LinkedIn or X.

### 3.6 Replies
- **Email replies** are picked up from your inbox if IMAP is set (§1.3): every tick with automatic
  sending, otherwise when an admin clicks **Check replies** on Outreach. Without IMAP, on the
  partner page, click **Record reply**, choose **Channel: Email** and paste what they said.
- **LinkedIn or X replies:** **Record reply** with **Channel: LinkedIn** (or X).

When a reply is recorded:
- the remaining emails in the sequence are cancelled, so nobody gets "just following up" after answering;
- the partner moves to **In conversation**, if it was at Identified or Contacted (not for an opt-out);
- the app sorts the reply as positive, neutral or negative, and you can override that. Opt-out
  wording ("unsubscribe", "remove me" and so on) is always honoured: the address is blocked
  permanently and the next step becomes "Opted out - do not contact".

Answer every reply yourself, from your own mailbox or LinkedIn, within one business day.

**Unsubscribes** (v0.13.2). Every email ends with a line telling the person to reply "unsubscribe", and
carries an unsubscribe link that mail apps show as an Unsubscribe button. Both arrive in the sending mailbox.
**Check replies** (or the scheduler) reads them: the address is never emailed again, the partner is marked
opted out, and anything queued for them is cancelled. If IMAP isn't set up for that mailbox, open the partner
and use **Record reply** with their words; "unsubscribe", "remove me", "opt out" and similar are always
treated as an opt-out. Our own footer quoted back in a normal reply is ignored.

### 3.7 Meetings, pilots and agreements
- After a call, **Log an interaction** with **Type: Meeting** (or Demo for a product demo). Meetings
  and demos count towards the campaign's **Meetings** figure and its goal.
- Move the stage as the deal moves: **In conversation → Pilot → Signed**. Use the stage bar at the
  top of the partner page, or drag the card on **Partners → Pipeline board**.
- **Partnership agreement** on the partner page: set the status (proposed → negotiating → signed),
  the date and the key terms. Signing marks the partner Signed and stops any queued email.

### 3.8 Log results by hand, only for what the app can't see
On the campaign page, **Log results** is for:
- opens and clicks from another email tool;
- signups and conversions;
- revenue;
- spend.

**Don't** enter emails sent, replies or meetings for partners in the campaign. Those are already
counted, and entering them again would double them.

### 3.9 Status
Change it from the dropdown at the top of the campaign:
- **active** while you're working it;
- **paused** while you wait on something, such as a website fix;
- **completed** when the end date passes.

Completing a campaign doesn't stop email. To stop email for a partner, cancel its queued messages
in Outreach or mark the partner declined.

---

## 4. LinkedIn connections import

### Why this way
LinkedIn doesn't let outside apps read your connections or send messages for you. Automation and
scraping tools break its terms and get accounts restricted. LinkedIn does let you download your own
data, and that's what Vanguard-GTM reads.

### Steps
1. **Download from LinkedIn.** In LinkedIn:
   - go to **Me → Settings & Privacy → Data privacy → Get a copy of your data**;
   - choose **"Want something in particular?"**, tick **Connections** only, and click **Request archive**;
   - LinkedIn emails a download link, usually within 10 minutes. Download it and unzip it to get `Connections.csv`.
2. **Import it.** In Vanguard-GTM:
   - go to **Partners** and click **Import LinkedIn connections**;
   - choose `Connections.csv`, then click **Import**.
3. **Read the result.** The import reports:
   - how many connections were loaded;
   - how many partners you know someone at;
   - which named contacts you're now connected with;
   - which contact emails were added because the person shared one with LinkedIn.

### What you get
- **Known** column on Partners: the number of the team's imported connections at each
  organisation.
- **People you know here** card on each partner: name, title, when you connected, whose import
  they came from and a link to their profile. The partner's named contact is marked **named contact**.
- **"Connected on LinkedIn"** entry on the partner's timeline, once, when the partner's named
  contact appears in an export (including someone you were already connected with). For someone
  you sent a request to, this is how the accepted request shows up. It doesn't count as a touch, because it's
  something they did, not something you did.
- **Contact email.** If the partner's named contact shared an email with LinkedIn and the partner
  has none, it becomes the partner's contact email. LinkedIn leaves the email blank for most people. That's
  normal.

### Habits
- **Re-import every Friday.** It only adds and refreshes; nothing is duplicated.
- **Each team member imports their own file.** The partner page then shows *whose* connection each
  person is, which tells you who should ask for the introduction.
- **Privacy:** the file holds your connections' personal details. Don't share it outside the team.
  To remove everything you imported, open **Import LinkedIn connections** and click **Remove my
  imported connections**.

Command line (admin, on the server, after copying the file into `/opt/vanguard-gtm/data/`):
```bash
sudo docker exec vanguard-gtm vanguard linkedin import /app/data/Connections.csv --by naren@atmakosh.com
sudo docker exec vanguard-gtm vanguard linkedin matches --property liqmint-institutional
```

### Introductions (v0.11.0)
Warm introductions beat any cold message. After importing the **full** archive (the .zip, not just
Connections.csv):

1. **Introductions → Find paths.** You get up to three people per target: **insiders** (they work there) and
   **likely bridges** (someone at a company in the target's background, or a close tie in the target's world).
2. For a bridge, click **Check 2nd-degree** first. It opens LinkedIn's search for the target, filtered to your
   2nd-degree network, so you can see who you actually share. LinkedIn's export doesn't include 2nd- or
   3rd-degree connections, so the app can't see that for you.
3. Tick the paths worth using → **Draft**. Each ask is a short double opt-in note ("say no if it isn't a fit")
   plus a paragraph they can forward. Edit it to sound like you.
4. An admin **approves**. **Send approved emails** emails the people who shared an address with LinkedIn; for
   everyone else, open the ask, **Copy & open LinkedIn**, send it there, then click **I sent it on LinkedIn**.
5. When they answer, record **Agreed to intro**, **Introduced** or **Declined**. It's logged on the target's
   page, and an introduction moves the target to Contacted.

Nobody is proposed for more than four introductions, so no one gets a pile of requests from you.

---

## 5. Track progress

### 5.1 The campaign page, top to bottom
| Part | What it tells you |
|---|---|
| **Sent / Replies / Meetings / Conversions / Spend** | Totals. Sent, Replies and Meetings include outreach for the campaign's partners ("N from outreach") plus anything logged by hand. Reply rate = replies ÷ partners touched (or emails sent, if higher). |
| **Goal bar** | Progress against the goal you set, for example 3 of 8 meetings |
| **Funnel** | Partners → Touched → Replied → In conversation → Pilot → Signed, with % of partners. Where the numbers drop off shows what to fix. |
| **Queue line** | Emails sent · LinkedIn/X touches · meetings · **drafts awaiting approval** · approved and queued (next due date) · **partners needing a contact email** |
| **Partner table** | One row per partner: stage, contact and email, emails sent of steps (and how many await approval), LinkedIn/X touches, replied, last touch, next step and its date |
| **Results log** | What was entered by hand |

How each measure is counted:

| Measure | Counts |
|---|---|
| Touched | Partners with at least one email sent or one LinkedIn/X message logged |
| Replied | Partners who replied on any channel, including opt-outs |
| Meetings | Interactions logged as Meeting or Demo |
| In conversation | Partners at In conversation, Pilot or Signed |

### 5.2 Other places to look
- **Campaigns list:** every campaign with its partner count, LinkedIn/X touches, sent, replies,
  meetings, conversions and revenue.
- **Outreach:** filter by **campaign** to see its emails by status (Needs approval, Queued, Sent,
  Replied, Stopped). The banner shows email mode, today's count against the cap, and reply sync.
- **Partners → Pipeline board:** every partner by stage, drag to move.
- **Dashboard:** per-property totals, including outreach drafts, approved, sent and replied.
- **Tripwires:** the Friday readings. The campaign page gives you the numbers for the LiqMint
  Institutional tripwires (meetings, replies, pilots).

From the server, a one-screen summary:
```bash
sudo docker exec vanguard-gtm vanguard campaign show 1
```

### 5.3 What good looks like for partner outreach
These are working assumptions to test, not promises:

| Stage | Healthy | If below, check |
|---|---|---|
| LinkedIn accept rate | 30–50% within 2 weeks | The note: is it personal, with one hook from their own work? |
| Reply rate (of touched) | 10–20% | The first line, and the ask: a question beats a pitch |
| Reply → meeting | 40%+ | Response speed: answer within one business day |
| Meeting → pilot | 1 in 4–6 | The offer: scoped, read-only, paid 6-week proof-of-value |

---

## 6. Weekly routine

| When | Who | Do |
|---|---|---|
| **Daily (10 minutes)** | Each sender | Check LinkedIn for accepts and replies. Send the saved follow-up to anyone who accepted, and log it (§3.5). Record any reply (§3.6). |
| **Daily** | Admin | Approve drafts on Outreach that are ready. If automatic sending is off, click **Send due now**. |
| **Monday** | Team | Each person picks 10–15 partners from the campaign table where Next step is due. Check **Known** first for a warm introduction. |
| **Friday** | Each person | Re-import LinkedIn connections (§4). |
| **Friday** | Admin | Open the campaign: read the funnel and the queue line. Record the week's tripwire readings on **Tripwires**. Move partners that have gone quiet after 2 touches to their next channel (warm intro, X, a different person), or mark them declined. |
| **End of campaign** | Owner | Set status to completed. Note what worked in the description. Start the next campaign and move the open partners into it. |

---

## 7. Rules that keep the plan from failing

1. **Approval before anything leaves.** Admins approve every email. LinkedIn and X messages are sent
   by a person.
2. **No guessed addresses, no automation tools on LinkedIn.**
3. **One channel at a time per person.** LinkedIn first for named people. Email only if LinkedIn
   stalls or they publish an inbox.
4. **Claim discipline.** Never claim customers, partners or integrations you don't have; never say
   LiqMint "supports" or is "live on" a network; never mention yield or returns. The lint gate
   blocks the worst cases, but you are the first check.
5. **Don't double-count.** Emails sent, replies and meetings for partners in a campaign are counted
   for you. Log by hand only what the app can't see.
6. **Two touches, then change something.** After two unanswered touches over about 10 days, move to
   a warm introduction, a different person or a different channel. Never send a third unanswered
   message on the same channel.

---

## 8. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Approved email isn't in my Sent folder | Outbox mode (the default) | Turn on SMTP (§1.2). The Outreach banner must say "Live email". |
| "no contact email on the partner yet" | The partner has no address | Add one (§2.2) |
| Nothing goes out although approved | Automatic sending is off and nobody clicked Send | Click **Send due now**, or set `VANGUARD_OUTREACH_EVERY_MIN` (§1.4) |
| Banner shows a problem in red | Missing SMTP or sender setting | Fix that line in `.env`, then `sudo docker compose up -d` |
| A reply didn't stop the sequence | IMAP is off; or automatic sending is off and nobody clicked **Check replies**; or they wrote a new email (not a reply) from another address | Click **Check replies**, or record the reply on the partner page (§3.6) |
| Campaign shows 0 touches | Partners aren't attached, or LinkedIn messages were logged as Note | Add the partners (§3.2). Log LinkedIn messages with Type **LinkedIn**. |
| Known is empty | No LinkedIn import yet, or the company name on LinkedIn differs | Import (§4). Very short or generic company names ("Bank") are deliberately not matched. |
| Import says "this is not LinkedIn's Connections.csv" | Another file from the archive was chosen | Choose `Connections.csv` from the unzipped archive |
| `git pull` says "dubious ownership" | The repo is owned by root | Use `sudo git pull` |

---

## 9. Quick reference

**Email status:** draft (needs approval) → approved (queued) → sent → replied, or stopped
(cancelled, failed, bounced).

**Partner stage:** identified → contacted → in conversation → pilot → signed (or declined).

**Interaction types:** Email (logged automatically when Outreach sends), LinkedIn, X, Call,
Meeting, Demo, Proposal, Note.

**Commands (admin, on the server, prefix with `sudo docker exec vanguard-gtm`):**
```
vanguard campaign list [--property P]
vanguard campaign show <id>
vanguard campaign attach <id> "<partner name>" …
vanguard campaign detach <id> "<partner name>" …
vanguard outreach status
vanguard outreach send
vanguard outreach sync-replies
vanguard linkedin import /app/data/Connections.csv --by <email>
vanguard linkedin matches [--property P]
```
