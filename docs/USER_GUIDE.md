# Vanguard-GTM — User Guide

Version 0.7.2 · updated 2026-09-28 · for the team (general users) and admins

Vanguard turns the agent's go-to-market plans into day-to-day work: campaigns you run and
measure, partners you work through a pipeline, and tasks you tick off. Everyone shares one
dashboard against the $2M ARR target for each property.

## Signing in
Open the address your admin gives you (for example `https://gtm.vireoka.com`, or
`http://localhost:8080` on your own machine) and sign in with your email and the temporary
password. Ask an admin to reset it if you forget it. Eight wrong attempts lock that email for
15 minutes.

**Light or dark theme:** use the switch at the bottom of the sidebar.

## Roles at a glance

| You can… | Team member | Admin |
|---|---|---|
| See everything: dashboard, campaigns, partners, tasks | ✔ | ✔ |
| Create and edit campaigns, log results | ✔ | ✔ |
| Delete a campaign or result entry | yours only | any |
| Add and edit partners, move them through stages, log calls and emails | ✔ | ✔ |
| Delete a partner | – | ✔ |
| Update a task's status and notes | tasks assigned to you | any |
| Create, delete, assign and prioritise tasks | – | ✔ |
| Set a property's ARR target | – | ✔ |
| Add named partners under a recommendation, edit email drafts, record replies, update agreements | ✔ | ✔ |
| Set a partner's email permission (opted in, opted out…) | ✔ | ✔ |
| Ask the agent to recommend partners; approve, send and cancel partner emails; check the inbox for replies; email the approval digest; sync Postmark suppressions | – | ✔ |
| Run the agent, approve plans, import them, sync to Notion | – | ✔ |
| Add and disable users, see the audit log | – | ✔ |

## Dashboard
- **Top row:** portfolio ARR run-rate against the combined target, revenue logged, active
  campaigns, partners in pilot or signed, and task completion.
- **Weekly charts:** revenue and meetings from logged results. The table icon switches a chart
  to a table.
- **Property cards:** each card shows:
  - its run-rate against target (the last 30 days of logged revenue × 12);
  - the funnel (sent → replies → meetings → conversions);
  - the partner pipeline by stage;
  - campaign and task counts.

  Admins see a pencil icon for editing the target.
- **My open tasks** and **Recent partner activity** sit at the bottom.

## Campaigns
1. **New campaign:** pick the property, type (email, social, partner, event, content, paid),
   status, dates, goal (for example 20 meetings), budget and owner.
2. **Log results** whenever you have new numbers from Smartlead, Instantly, LinkedIn, GA4 or
   your CRM. Enter only what changed since the last entry. Totals, reply rate, cost per
   conversion and goal progress update straight away.
3. **Status:** draft → scheduled → active → paused → completed. Change it from the dropdown at
   the top of the campaign.
4. **Agent campaigns:** those imported from the agent carry the full five-step email sequence
   or the social hooks. Sending still happens in your email tool, only after an admin approves
   the plan.

## Partners
- The **board** has a column per stage: identified → contacted → in conversation → pilot →
  signed, plus declined. Drag a card to another column, or use the "Move to" menu on the card.
- **Partnership types:**
  - *Design partner*: an early customer co-building a scoped pilot.
  - *Co-sell*: a B2B partner selling alongside us.
  - *Distribution*, *referral/affiliate* and *integration* cover the other channels.
- **Open a partner** to log an interaction (email, call, meeting, demo, proposal, note) with
  its outcome and next step. You can move the stage in the same step. The timeline keeps the
  full history.

## Partner outreach: from recommendation to signed agreement

The agent works like a partnerships expert. For each property it recommends who to partner with
and why, ranks them, and drafts the first emails. For Jodibana, for example, it recommends:
- South Asian wedding planners;
- wedding photographers;
- destination wedding resorts and hotels;
- banquet halls in diaspora hubs;
- temples and community associations;
- bridal and jewellery boutiques.

1. **Recommend** (admin): Partners → **Recommend partners** → pick the property.
   - **Expert playbook** is instant and free.
   - **Agent names organisations** has your local model suggest specific businesses.

   Each recommendation gets:
   - a **priority** (P0 = approach first) and a score from 0 to 100, built from five factors:
     ICP fit, reach, access, strategic value and speed to result;
   - a partnership type: *design partner* (co-builds a pilot), *co-sell* (sells alongside us),
     *referral/affiliate*, *distribution* or *integration*;
   - why it fits, the typical deal, and how to find the right contact;
   - a 3-step email sequence: intro, follow-up after about 4 days, polite close after about 9.
2. **Name real targets:** most recommendations are **segments**, such as "South Asian wedding
   planners". Open one and use **Named targets** to add the specific businesses you've found,
   with a contact email. Each named business gets its own copy of the emails, personalised with
   its name and the contact's first name.
3. **Review the emails** on the partner page or on the **Outreach** page. Anyone can edit a
   draft. Edits are checked against our claim rules: no invented customers, guarantees or
   unsourced numbers.
4. **Approve** (admin): approve single emails, or a partner's whole sequence with **Approve 3**.
   Nothing is ever sent without an admin's approval, and any edit needs a fresh approval.
5. **Send** (admin): Outreach → **Send due now**.
   - The first email goes straight away.
   - Follow-ups go only when their delay has passed and nobody has replied.
   - A daily cap and the opt-out list are always respected.
   - In **Outbox mode** (the default), emails are saved as files instead of sent, so you can see
     exactly what would go out. An admin switches to live email once the mailbox is set up
     (setup guide Part 7).
6. **Replies:**
   - If the inbox is connected, **Check replies** picks them up automatically.
   - Otherwise, use **Record reply** on the partner page for any response: email, phone or
     LinkedIn.

   A reply stops the remaining emails and moves the partner to *In conversation*. "Unsubscribe"
   or "remove me" means we never email that address again.
7. **Email permission** (on the partner page, above the sequence): record whether the partner
   has agreed to hear from us.
   - *No permission yet* (cold): the default.
   - *Opted in* or *Existing relationship*: they've agreed, or already know us.
   - *Replied*: set automatically when they answer.
   - *Opted out*: stops every queued email and we never email them again.

   When your admin has switched on **Postmark**, only partners with permission are emailed
   through it. First emails to cold partners go from our own mailbox, or wait (the send report
   says "held").
8. **Agreement:** on the partner page, move the agreement from *proposed* to *negotiating* to
   *signed*, with the date and key terms. Signed agreements show on the dashboard, for each
   property and in total.

### When Postmark is on
The Outreach page shows a **Postmark streams** banner:
- which stream carries partner emails and which carries team alerts;
- how replies come in;
- how many emails went out this month against the monthly cap (100 on the free plan).

Each sent email shows how it went (*postmark* or *smtp*) and, where known, *delivered* or
*opened*.

What happens automatically:
- **Replies:** if inbound is on, a reply moves the partner to *In conversation* straight away.
  Admins and the partner's owner get an email alert.
- **Bounces and spam complaints:** the sequence stops and the address is never emailed again.

Admin tools:
- **Email approval digest** sends every admin the list of drafts waiting for approval.
- **Sync suppressions** lines up our do-not-email list with Postmark's.

### Researched partners: real organisations to approach
Admins can click **Load researched partners** on the Partners page. It adds about 117 real
organisations across all eight properties, each checked against its own website or recent news.
For example:
- U.S. Bank, BNY and Fireblocks for LiqMint Institutional;
- the India Association of Minnesota and TANA for Jodibana and JodiUSA;
- gener8tor, MN Cup and Toastmasters for OratoPlus.

Each organisation:
- has a **researched** badge, its website, why it fits (with a clickable source) and its contact
  page;
- gets its own copy of the three draft emails, which still need an admin's approval.

Most large organisations don't publish a partnerships inbox. For those, the queue shows "needs
contact email": use the contact page or partner program linked on the partner, find the right
person, and add their business email (Edit). Loading again is safe; it never duplicates partners
or overwrites an email you entered.

## Tasks
- The agent's 30-day plan for each property, plus tasks admins add by hand (ids like `ORA-M001`).
- **Filters:** property, status (the four counters at the top), "Only mine", and search.
- **Team members** change the status of tasks assigned to them. Tasks assigned to someone else
  show a lock.
- **Admins** set the assignee, priority and due date inline, add tasks with **New task**, and
  delete them.

## Admin → Agent & runs
1. **Check the configuration** card:
   - whether the local model is ready;
   - whether Claude paid runs are off ($0) or on with a cap;
   - which keys are set.
2. **Start a run:**
   - pick properties (or all 8);
   - choose **Dry run** (placeholder content, $0) or **Real run** (local model, $0);
   - a Claude-only run happens only if the server's spend cap is set.
3. **Open a run:**
   - view each playbook: revenue roadmap, ICP, partnerships, notes, lint findings;
   - **Approve** plans whose copy passed the claim checks;
   - **Import** to turn them into draft campaigns and identified partners;
   - **Sync to Notion** pushes the tasks to your Notion databases.

## Admin → Users and Audit log
- **Users:**
  - **Add user** with a temporary password of at least 10 characters. Share it privately.
  - Change a role with the dropdown.
  - Click the status badge to disable or enable an account. This takes effect immediately.
  - The key icon resets a password.
- **Audit log:** every sign-in and change, with who made it and when.

## Demo data
An admin can load a labelled sample to show the app around:
- `vanguard demo-data` loads it;
- `vanguard demo-data --purge` removes it.

Every sample record is named `[DEMO]`, and none of its numbers are real.


## Tripwires and gates (v0.7.0)

Open **Tripwires** in the sidebar and pick a property. Each row is one warning signal with the
week it is checked (always a Friday) and what to do if it trips.

- **Record a reading** every time the signal changes, and every week for the weekly ones. A check
  with no reading shows amber: missing evidence is never green.
- **Gates** are the things that must be true before launch. Only an admin can pass or fail one.
  While a gate is open, the agent will not plan the tasks it blocks (for example investor outreach
  or paid ads).
- **Interim owner** means the founder is supervising the property through AI agents until a CEO is named. Its "CEO named" gate is due Jan 15, 2027, and paid ads stay blocked until it passes.
- **HALT** appears when three signals have tripped. Stop, don't adjust the plan, and talk to the
  property owner about the walk-away conditions.
