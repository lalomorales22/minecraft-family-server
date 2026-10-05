# How to Connect - Family Minecraft Server

Everyone joins the **same world** ("FamilyWorld") that lives on your Mac server.
You do NOT create a new world on your console - just connect to the server and you're all in the same world together.

---

## Step 1: Find the Server IP

On your Mac, run `./start.sh`. It prints the server IP and opens the dashboard (http://localhost:8080), whose **How to Join** box shows these same steps with the IP already filled in.

Use this IP wherever you see `<YOUR_MAC_IP>` below.

(This can change if the router assigns a new IP. Run `./start.sh` again if things stop working — it tells you if the IP changed.)

---

## Step 2: Set Up DNS on Each Console

This is a one-time setup. It tells your console to route through BedrockConnect so you can enter a custom server address.

### Nintendo Switch

1. Go to **System Settings** > **Internet** > **Internet Settings**
2. Select your Wi-Fi network and press **Change Settings**
3. Scroll down to **DNS Settings** and change to **Manual**
4. Set **Primary DNS** to: `<YOUR_MAC_IP>`
5. Set **Secondary DNS** to: `8.8.8.8`
6. Save and connect

### PlayStation 5

1. Go to **Settings** > **Network** > **Settings** > **Set Up Internet Connection**
2. Select your Wi-Fi network
3. Press the **Options** button and choose **Advanced Settings**
4. Set **DNS Settings** to **Manual**
5. Set **Primary DNS** to: `<YOUR_MAC_IP>`
6. Set **Secondary DNS** to: `8.8.8.8`
7. Save and connect

---

## Step 3: Connect to the Family Server

This is the same on every console:

1. Open **Minecraft**
2. Press **Play**
3. Go to the **Servers** tab (far right)
4. Pick **The Hive** (Lifeboat, Mineville, Galaxite and Enchanted Dragons also work - other Featured Servers don't)
5. It will connect to **BedrockConnect** instead (a menu with a server list)
6. You'll see **"Family Server"** in the list - select it and join

If you don't see it in the list, choose **"Connect to a Server"** and enter:
- **Server Address:** `<YOUR_MAC_IP>`
- **Port:** `19133`

---

## Step 4: Playing Together

That's it - there is no step 4. Once each person joins the server, you're all in the same "FamilyWorld" together. The world is saved on the Mac, so progress is kept even when consoles are turned off.

---

## Quick Checklist

| What | Status |
|------|--------|
| Ran `./start.sh` on the Mac? | Once - it keeps running in the background |
| Dashboard Setup Check all green? | http://localhost:8080 |
| Console DNS set to Mac IP? | One-time setup |
| Xbox Live / Microsoft account signed in? | Required on each console |
| Same Wi-Fi network as the Mac? | Required |
| Nintendo Switch Online (Switch) / PlayStation Plus (PlayStation)? | Needed to open the Servers tab. See the README for a PlayStation LAN route |

---

## Troubleshooting

**"Unable to connect to world"**
- Run `./start.sh` on the Mac and check the dashboard's Setup Check is all green
- Make sure the console is on the same Wi-Fi network
- Check that the server IP hasn't changed

**BedrockConnect menu doesn't appear (goes to the real Featured Server instead)**
- Pick The Hive, Lifeboat, Mineville, Galaxite or Enchanted Dragons - other Featured Servers aren't redirected
- Double-check the DNS settings - Primary DNS must be the Mac IP
- Restart Minecraft fully (close and reopen the app)

**Kicked or can't join**
- Everyone needs to be signed into a Microsoft/Xbox Live account (it's free)
- The server allows up to 10 players

**Server IP changed**
- Run `./start.sh` again and check the new IP it prints
- Update the DNS on each console to the new IP
