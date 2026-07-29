# Livestream, Raffles & Auctions - User Guide

This guide explains how to set up and run a livestream event with raffles and/or auctions using the House of Beers admin panel.

---

## What You Need

- Access to the admin panel: https://appadmin.houseofbeers.nl/admin/
- A YouTube livestream link (you start the stream on YouTube separately)
- Your admin login credentials

---

## Quick Overview

| Feature | What it does |
|---------|-------------|
| **Livestream** | Embeds your YouTube stream in the app with live chat |
| **Raffle** | Randomly picks winners from people watching the stream |
| **Auction** | Shows items one-by-one; you manually set the winner and final price |

Everything is managed from the admin panel while the stream is running. The app updates automatically for viewers.

---

## Step 1: Create the Event

1. Go to **Admin Panel** > **Events** > **Events**
2. Click **"Add Event"** (top right)
3. Fill in the fields:

| Field | What to enter |
|-------|--------------|
| **Title** | Name of your event (e.g., "Friday Night Beer Tasting") |
| **Description** | Short description shown to users |
| **Event type** | Choose: `livestream` (for raffles) or `auction` (for auctions) |
| **Scheduled at** | Date and time the event starts |
| **YouTube URL** | Your YouTube stream link (e.g., `https://youtube.com/live/abc123`) |
| **Image URL** | Optional event cover image URL |
| **Status** | Leave as **Scheduled** for now |

### Adding Raffles (optional)

Scroll down to the **Raffles** section at the bottom of the event form:

1. Click **"Add another Raffle"**
2. Fill in:
   - **Prize name**: What the winner gets (e.g., "6-pack IPA Gift Box")
   - **Num winners**: How many winners to draw (e.g., 1)
3. Repeat for each prize you want to raffle
4. Leave **Status** as `Pending` — you'll draw winners later during the stream

### Adding Auction Items (optional)

Scroll down to the **Auction items** section at the bottom of the event form:

1. Click **"Add another Auction item"**
2. Fill in:
   - **Title**: Item name (e.g., "Rare Barrel-Aged Stout 2019")
   - **Image URL**: Photo of the item (optional)
   - **Starting price**: Minimum bid price in euros
3. Repeat for each item
4. Leave **Status** as `Pending` — you'll activate items one-by-one during the stream

5. Click **Save**

---

## Step 2: Go Live

When you're ready to start:

1. **Start your YouTube livestream** first (via YouTube Studio or your streaming software)
2. Go to **Admin Panel** > **Events** > **Events**
3. Find your event in the list
4. Change the **Status** dropdown to **Live**
5. Click **Save**

The event now shows as "LIVE" in the app. Users can tap "Join Live" to watch and chat.

> **Tip:** You can also select the event checkbox and use the **"Set selected events to LIVE"** action from the dropdown at the top.

---

## Step 3: During the Stream

### Chat

Chat works automatically. Users type messages in the app and everyone sees them in real-time. You don't need to do anything for chat — it runs on its own.

If you want to send a **system message** (highlighted announcement visible to everyone):

1. Go to **Admin Panel** > **Events** > **Event messages**
2. Click **"Add Event Message"**
3. Select the event, type your message, and check **"Is system"**
4. Save — it appears as a gold highlighted message in the chat

### Viewer Count

The admin panel shows a live viewer count next to each event. A viewer is counted as "active" if they've been on the stream page in the last 90 seconds.

---

## Running a Raffle

Raffles pick random winners from people currently watching the stream.

### How to Draw Winners

1. Go to **Admin Panel** > **Events** > **Raffles**
2. You'll see your raffle(s) listed with status `Pending`
3. **Select the checkbox** next to the raffle(s) you want to draw
4. From the **Action dropdown** at the top, select **"Draw winners for selected raffles"**
5. Click **"Go"**

That's it! The system will:
- Look at who is currently watching (active in the last 90 seconds)
- Randomly pick the number of winners you specified
- Make sure nobody wins twice in the same event
- Show an animated winner announcement in the app to all viewers

### After Drawing

- Winners are shown in the app's **Winners modal** (trophy icon)
- You can see all winners in **Admin Panel** > **Events** > **Raffle winners**
- To export winners: select them and use the **"Export winners as CSV"** action

### Oops, Need a Redraw?

If something went wrong:

1. Go to **Raffles** in the admin
2. Select the raffle(s)
3. Use the **"Reset all winners for the event"** action
4. This clears all winners and resets raffles to `Pending`
5. Draw again when ready

---

## Running an Auction

Auctions show one item at a time to viewers. Bidding happens verbally during the livestream (via YouTube chat or voice) — you manually record the final price and winner in the admin.

### How to Run an Auction

#### 1. Activate the First Item

1. Go to **Admin Panel** > **Events** > **Auction items**
2. Find the item you want to auction first
3. **Select its checkbox**
4. From the **Action dropdown**, select **"Set selected item as ACTIVE"**
5. Click **"Go"**

The item now appears in the app for all viewers with its title and starting price. Only one item can be active at a time — activating a new item automatically deactivates the previous one.

#### 2. Announce the Item on Stream

Tell your viewers about the item on the YouTube stream. Let them bid via YouTube chat or however you prefer.

#### 3. Close the Bidding

When bidding is done:

1. Go to the **Auction item** in the admin (click on its title)
2. Set **Final price** to the winning bid amount
3. Set **Winner** to the winning user (search by name/email)
4. Change **Status** to **Sold**
5. Click **Save**

The app shows an animated "Sold!" banner to all viewers with the item name, price, and winner.

#### 4. Next Item

Repeat: activate the next item, auction it, record the winner.

#### If an Item Doesn't Sell

Just change its status to `Sold` without setting a winner or final price, or leave it as `Pending`.

### Exporting Results

1. Go to **Admin Panel** > **Events** > **Auction items**
2. Select the items
3. Use the **"Export auction results as CSV"** action
4. You get a file with: item, starting price, final price, winner email, winner name

---

## Step 4: End the Event

When the stream is over:

1. Go to **Admin Panel** > **Events** > **Events**
2. Change the event **Status** to **Ended**
3. Save

The event will no longer show on the app's home screen.

> **Tip:** You can use the **"Set selected events to ENDED"** bulk action.

---

## Checklist: Before You Go Live

- [ ] Event created in admin with correct date/time
- [ ] YouTube stream link added to the event
- [ ] Event type set correctly (`livestream` or `auction`)
- [ ] Raffle prizes added (if doing a raffle)
- [ ] Auction items added with starting prices (if doing an auction)
- [ ] YouTube stream is running
- [ ] Event status changed to **Live**

## Checklist: During the Stream

- [ ] Activate auction items one-by-one (if auction)
- [ ] Draw raffle winners when ready (if raffle)
- [ ] Record auction winners + final prices (if auction)

## Checklist: After the Stream

- [ ] Set event status to **Ended**
- [ ] Export raffle winners or auction results as CSV if needed

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Viewers can't see the stream | Check that the YouTube URL is correct and the YouTube stream is actually live |
| No one shows up in raffle draw | Users must be actively watching (visited the stream page in the last 90 seconds) |
| Raffle says "0 winners drawn" | Not enough active viewers, or all viewers already won in this event |
| Auction item not showing in app | Make sure you used the "Set as ACTIVE" action — only one item is active at a time |
| Chat messages not appearing | The app checks for new messages every 3 seconds — wait a moment |
| Viewer count seems low | Only counts users who have the stream page open right now (last 90 seconds) |
| Wrong winner drawn in raffle | Use "Reset all winners for the event" action and redraw |

---

## FAQ

**Q: Do viewers need to do anything special to enter a raffle?**
A: No. Anyone watching the livestream is automatically eligible. They just need to have the stream page open in the app.

**Q: Can I do both a raffle AND an auction in the same event?**
A: Yes, but set the event type to `auction` so the auction panel shows. Raffles work regardless of event type.

**Q: How does bidding work for auctions?**
A: Bidding happens on the YouTube stream (voice/chat). The app only shows the current item and results — you manually enter the winner and price in the admin.

**Q: Can I add more raffle prizes or auction items after the event is live?**
A: Yes. Go to the event in the admin and add them. They'll appear in the app within a few seconds.

**Q: What YouTube URL format should I use?**
A: Any of these work:
- `https://www.youtube.com/watch?v=VIDEO_ID`
- `https://youtube.com/live/VIDEO_ID`
- `https://youtu.be/VIDEO_ID`
