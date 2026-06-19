"""
================================================================================
OSINT.PY - Comprehensive Open Source Intelligence Engine
================================================================================
Provides 30+ OSINT categories for reconnaissance and intelligence gathering.
All methods use only stdlib + aiohttp (already a project dependency).

Categories: Username, Email, Domain, IP/MAC, Social Networks, IM, People Search,
Dating, Phone Numbers, Public/Business Records, Transportation, Geolocation,
Search Engines, Forums/Blogs, Archives, Translation, Metadata, Dark Web,
Digital Currency, Classifieds, Encoding/Decoding, AI Tools, Malware Analysis,
Exploits, Threat Intel, OpSec, Documentation/Evidence, Training
================================================================================
"""

import os
import sys
import csv
import tempfile
import re
import json
import socket
import ssl
import asyncio
import hashlib
import base64
import struct
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlparse, quote, urlencode
from dataclasses import dataclass, field
import logging
import ipaddress
import time
import functools
import random

# Load .env for API keys (OPENROUTER_API_KEY, SERPER_API_KEY, SEARXNG_URL)
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))
except ImportError:
    pass  # python-dotenv not installed, keys must be set via environment

logger = logging.getLogger(__name__)

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# =============================================================================
# Data Models
# =============================================================================

@dataclass
class OSINTResult:
    """Result from an OSINT query"""
    category: str
    query: str
    data: Dict[str, Any] = field(default_factory=dict)
    sources: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'category': self.category, 'query': self.query,
            'data': self.data, 'sources': self.sources,
            'timestamp': self.timestamp, 'success': self.success,
            'error': self.error
        }

    def summary(self) -> str:
        lines = [f"\n{'='*60}", f"OSINT: {self.category}", f"Query: {self.query}",
                 f"Time:  {self.timestamp}", '='*60]
        if not self.success:
            lines.append(f"ERROR: {self.error}")
            return '\n'.join(lines)
        for k, v in self.data.items():
            if isinstance(v, list):
                lines.append(f"\n{k}:")
                for item in v[:20]:
                    lines.append(f"  - {item}")
                if len(v) > 20:
                    lines.append(f"  ... and {len(v)-20} more")
            elif isinstance(v, dict):
                lines.append(f"\n{k}:")
                for sk, sv in v.items():
                    lines.append(f"  {sk}: {sv}")
            else:
                lines.append(f"{k}: {v}")
        return '\n'.join(lines)


# =============================================================================
# OSINT Resource Database - Links & Tools for each category
# =============================================================================

OSINT_RESOURCES = {
    "username": {
        "tools": [
            {"name": "Namechk", "url": "https://namechk.com/", "desc": "Username availability checker"},
            {"name": "WhatsMyName", "url": "https://whatsmyname.app/", "desc": "Username enumeration"},
            {"name": "Sherlock", "url": "https://github.com/sherlock-project/sherlock", "desc": "Hunt usernames across social networks"},
            {"name": "Maigret", "url": "https://github.com/soxoj/maigret", "desc": "Collect info by username"},
            {"name": "Instant Username", "url": "https://instantusername.com/", "desc": "Check username across platforms"},
            {"name": "KnowEm", "url": "https://knowem.com/", "desc": "Brand/username search 500+ sites"},
            {"name": "UserRecon", "url": "https://github.com/thelinuxchoice/userrecon", "desc": "Find usernames across 75 sites"},
        ]
    },
    "email": {
        "tools": [
            {"name": "Hunter.io", "url": "https://hunter.io/", "desc": "Email finder and verifier"},
            {"name": "Have I Been Pwned", "url": "https://haveibeenpwned.com/", "desc": "Breach database search"},
            {"name": "EmailRep", "url": "https://emailrep.io/", "desc": "Email reputation lookup"},
            {"name": "Epieos", "url": "https://epieos.com/", "desc": "Email OSINT tool"},
            {"name": "Holehe", "url": "https://github.com/megadose/holehe", "desc": "Check email on 120+ sites"},
            {"name": "Phonebook.cz", "url": "https://phonebook.cz/", "desc": "Email/domain/URL search"},
            {"name": "MailTester", "url": "https://mailtester.com/", "desc": "Email server validation"},
            {"name": "ThatsThem", "url": "https://thatsthem.com/", "desc": "Reverse email lookup"},
        ]
    },
    "domain": {
        "tools": [
            {"name": "WHOIS Lookup", "url": "https://whois.domaintools.com/", "desc": "Domain registration info"},
            {"name": "SecurityTrails", "url": "https://securitytrails.com/", "desc": "DNS history and subdomains"},
            {"name": "crt.sh", "url": "https://crt.sh/", "desc": "Certificate transparency search"},
            {"name": "Shodan", "url": "https://www.shodan.io/", "desc": "Internet-connected device search"},
            {"name": "BuiltWith", "url": "https://builtwith.com/", "desc": "Technology profiler"},
            {"name": "Wappalyzer", "url": "https://www.wappalyzer.com/", "desc": "Tech stack identifier"},
            {"name": "DNSDumpster", "url": "https://dnsdumpster.com/", "desc": "DNS recon and research"},
            {"name": "ViewDNS", "url": "https://viewdns.info/", "desc": "DNS and IP tools"},
            {"name": "Subfinder", "url": "https://github.com/projectdiscovery/subfinder", "desc": "Subdomain discovery"},
            {"name": "URLScan", "url": "https://urlscan.io/", "desc": "URL and website scanner"},
        ]
    },
    "ip_mac": {
        "tools": [
            {"name": "IPInfo", "url": "https://ipinfo.io/", "desc": "IP geolocation and ASN"},
            {"name": "AbuseIPDB", "url": "https://www.abuseipdb.com/", "desc": "IP abuse reports"},
            {"name": "GreyNoise", "url": "https://viz.greynoise.io/", "desc": "Internet noise analysis"},
            {"name": "Censys", "url": "https://search.censys.io/", "desc": "Internet-wide scan data"},
            {"name": "MAC Vendor Lookup", "url": "https://macvendors.com/", "desc": "MAC address vendor ID"},
            {"name": "Wigle", "url": "https://wigle.net/", "desc": "WiFi network mapping"},
            {"name": "BGPView", "url": "https://bgpview.io/", "desc": "BGP routing data"},
            {"name": "IPVoid", "url": "https://www.ipvoid.com/", "desc": "IP blacklist check"},
        ]
    },
    "images_videos_docs": {
        "tools": [
            {"name": "TinEye", "url": "https://tineye.com/", "desc": "Reverse image search"},
            {"name": "Google Images", "url": "https://images.google.com/", "desc": "Reverse image search"},
            {"name": "Yandex Images", "url": "https://yandex.com/images/", "desc": "Reverse image search (best for faces)"},
            {"name": "FotoForensics", "url": "https://fotoforensics.com/", "desc": "Image forensics (ELA)"},
            {"name": "ExifTool", "url": "https://exiftool.org/", "desc": "Metadata reader/writer"},
            {"name": "InVID", "url": "https://www.invid-project.eu/", "desc": "Video verification"},
            {"name": "Jeffrey EXIF Viewer", "url": "http://exif.regex.info/", "desc": "Online EXIF viewer"},
            {"name": "Remove.bg", "url": "https://www.remove.bg/", "desc": "Background removal"},
        ]
    },
    "social_networks": {
        "tools": [
            {"name": "Social Searcher", "url": "https://www.social-searcher.com/", "desc": "Social media search"},
            {"name": "Pipl", "url": "https://pipl.com/", "desc": "People search engine"},
            {"name": "Maltego", "url": "https://www.maltego.com/", "desc": "Link analysis tool"},
            {"name": "SpiderFoot", "url": "https://www.spiderfoot.net/", "desc": "OSINT automation"},
            {"name": "SocialBlade", "url": "https://socialblade.com/", "desc": "Social media statistics"},
            {"name": "Twint", "url": "https://github.com/twintproject/twint", "desc": "Twitter scraper"},
            {"name": "Instaloader", "url": "https://instaloader.github.io/", "desc": "Instagram scraper"},
            {"name": "OSINT Framework", "url": "https://osintframework.com/", "desc": "OSINT tool directory"},
        ],
        "platforms_to_check": [
            "https://www.facebook.com/{}", "https://www.instagram.com/{}/",
            "https://twitter.com/{}", "https://x.com/{}",
            "https://www.tiktok.com/@{}", "https://www.youtube.com/@{}",
            "https://www.linkedin.com/in/{}", "https://www.reddit.com/user/{}",
            "https://github.com/{}", "https://www.pinterest.com/{}/",
            "https://www.snapchat.com/add/{}", "https://t.me/{}",
            "https://www.twitch.tv/{}", "https://open.spotify.com/user/{}",
            "https://soundcloud.com/{}", "https://vimeo.com/{}",
            "https://www.flickr.com/people/{}", "https://medium.com/@{}",
            "https://dev.to/{}", "https://www.behance.net/{}",
            "https://dribbble.com/{}", "https://keybase.io/{}",
            "https://www.producthunt.com/@{}", "https://hackerrank.com/{}",
            "https://leetcode.com/{}", "https://stackoverflow.com/users/{}",
            "https://bitbucket.org/{}/", "https://gitlab.com/{}",
            "https://www.patreon.com/{}", "https://ko-fi.com/{}",
            "https://about.me/{}", "https://mastodon.social/@{}",
            "https://www.quora.com/profile/{}", "https://myspace.com/{}",
            "https://www.dailymotion.com/{}", "https://rumble.com/user/{}",
        ]
    },
    "instant_messaging": {
        "tools": [
            {"name": "Telegram Search", "url": "https://t.me/", "desc": "Telegram user/channel search"},
            {"name": "Discord Lookup", "url": "https://discord.com/", "desc": "Discord user search"},
            {"name": "Signal", "url": "https://signal.org/", "desc": "Secure messaging"},
            {"name": "Skype Resolver", "url": "https://www.skyperesolver.net/", "desc": "Skype IP resolver"},
            {"name": "WhatsApp", "url": "https://wa.me/", "desc": "WhatsApp number check"},
        ]
    },
    "people_search": {
        "tools": [
            {"name": "Pipl", "url": "https://pipl.com/", "desc": "Deep people search"},
            {"name": "ThatsThem", "url": "https://thatsthem.com/", "desc": "Free people search"},
            {"name": "Whitepages", "url": "https://www.whitepages.com/", "desc": "Phone/address lookup"},
            {"name": "TruePeopleSearch", "url": "https://www.truepeoplesearch.com/", "desc": "Free people search"},
            {"name": "Spokeo", "url": "https://www.spokeo.com/", "desc": "People search aggregator"},
            {"name": "BeenVerified", "url": "https://www.beenverified.com/", "desc": "Background checks"},
            {"name": "PeekYou", "url": "https://www.peekyou.com/", "desc": "People search"},
            {"name": "FamilyTreeNow", "url": "https://www.familytreenow.com/", "desc": "Public records"},
        ]
    },
    "dating": {
        "tools": [
            {"name": "Profile Searcher", "url": "https://www.profilesearcher.com/", "desc": "Dating profile search"},
            {"name": "SocialCatfish", "url": "https://socialcatfish.com/", "desc": "Catfish investigation"},
            {"name": "Tinder Search", "url": "https://tinder.com/", "desc": "Check username/profile"},
        ]
    },
    "phone_numbers": {
        "tools": [
            {"name": "NumVerify", "url": "https://numverify.com/", "desc": "Phone validation API"},
            {"name": "TrueCaller", "url": "https://www.truecaller.com/", "desc": "Caller ID and spam block"},
            {"name": "PhoneInfoga", "url": "https://github.com/sundowndev/phoneinfoga", "desc": "Phone number OSINT"},
            {"name": "Sync.me", "url": "https://sync.me/", "desc": "Caller ID lookup"},
            {"name": "CallerID Test", "url": "https://calleridtest.com/", "desc": "Phone number lookup"},
            {"name": "Twilio Lookup", "url": "https://www.twilio.com/lookup", "desc": "Phone intelligence"},
        ]
    },
    "public_records": {
        "tools": [
            {"name": "PACER", "url": "https://pacer.uscourts.gov/", "desc": "US court records"},
            {"name": "EDGAR", "url": "https://www.sec.gov/edgar/", "desc": "SEC filings"},
            {"name": "OpenCorporates", "url": "https://opencorporates.com/", "desc": "Corporate registry"},
            {"name": "Court Listener", "url": "https://www.courtlistener.com/", "desc": "Legal opinions/filings"},
            {"name": "GovInfo", "url": "https://www.govinfo.gov/", "desc": "US government info"},
            {"name": "FOIA.gov", "url": "https://www.foia.gov/", "desc": "Freedom of Information"},
        ]
    },
    "business_records": {
        "tools": [
            {"name": "OpenCorporates", "url": "https://opencorporates.com/", "desc": "Global company data"},
            {"name": "Crunchbase", "url": "https://www.crunchbase.com/", "desc": "Company/investor data"},
            {"name": "LinkedIn Company", "url": "https://www.linkedin.com/company/", "desc": "Company profiles"},
            {"name": "Glassdoor", "url": "https://www.glassdoor.com/", "desc": "Company reviews"},
            {"name": "D&B", "url": "https://www.dnb.com/", "desc": "Business credit reports"},
            {"name": "BBB", "url": "https://www.bbb.org/", "desc": "Better Business Bureau"},
        ]
    },
    "transportation": {
        "tools": [
            {"name": "FlightRadar24", "url": "https://www.flightradar24.com/", "desc": "Live flight tracker"},
            {"name": "MarineTraffic", "url": "https://www.marinetraffic.com/", "desc": "Ship tracking"},
            {"name": "FlightAware", "url": "https://flightaware.com/", "desc": "Flight tracking"},
            {"name": "ADSB Exchange", "url": "https://globe.adsbexchange.com/", "desc": "ADS-B aircraft data"},
            {"name": "VesselFinder", "url": "https://www.vesselfinder.com/", "desc": "Vessel tracking"},
            {"name": "License Plate Lookup", "url": "https://www.faxvin.com/", "desc": "Vehicle history"},
        ]
    },
    "geolocation": {
        "tools": [
            {"name": "Google Maps", "url": "https://maps.google.com/", "desc": "Mapping and street view"},
            {"name": "Google Earth", "url": "https://earth.google.com/", "desc": "Satellite imagery"},
            {"name": "GeoGuessr", "url": "https://www.geoguessr.com/", "desc": "Geolocation game/training"},
            {"name": "SunCalc", "url": "https://www.suncalc.org/", "desc": "Sun position calculator"},
            {"name": "Sentinel Hub", "url": "https://www.sentinel-hub.com/", "desc": "Satellite imagery"},
            {"name": "Wikimapia", "url": "https://wikimapia.org/", "desc": "Collaborative mapping"},
            {"name": "OpenStreetMap", "url": "https://www.openstreetmap.org/", "desc": "Open map data"},
            {"name": "What3Words", "url": "https://what3words.com/", "desc": "3-word addressing"},
        ]
    },
    "search_engines": {
        "tools": [
            {"name": "Google", "url": "https://www.google.com/", "desc": "Primary search"},
            {"name": "Bing", "url": "https://www.bing.com/", "desc": "Microsoft search"},
            {"name": "DuckDuckGo", "url": "https://duckduckgo.com/", "desc": "Privacy search"},
            {"name": "Yandex", "url": "https://yandex.com/", "desc": "Russian search engine"},
            {"name": "Baidu", "url": "https://www.baidu.com/", "desc": "Chinese search engine"},
            {"name": "Ahmia", "url": "https://ahmia.fi/", "desc": "Tor hidden service search"},
            {"name": "Startpage", "url": "https://www.startpage.com/", "desc": "Privacy Google proxy"},
            {"name": "Carrot2", "url": "https://search.carrot2.org/", "desc": "Clustering search"},
        ]
    },
    "forums_blogs": {
        "tools": [
            {"name": "BoardReader", "url": "https://boardreader.com/", "desc": "Forum search"},
            {"name": "Reddit Search", "url": "https://www.reddit.com/search/", "desc": "Reddit search"},
            {"name": "Google Groups", "url": "https://groups.google.com/", "desc": "Usenet/group search"},
            {"name": "4chan Archive", "url": "https://archive.4plebs.org/", "desc": "4chan archives"},
            {"name": "Nitter", "url": "https://nitter.net/", "desc": "Twitter frontend"},
        ]
    },
    "archives": {
        "tools": [
            {"name": "Wayback Machine", "url": "https://web.archive.org/", "desc": "Website archive"},
            {"name": "Archive.today", "url": "https://archive.ph/", "desc": "Web page snapshot"},
            {"name": "CachedView", "url": "https://cachedview.nl/", "desc": "Google cache viewer"},
            {"name": "CommonCrawl", "url": "https://commoncrawl.org/", "desc": "Web crawl data"},
        ]
    },
    "translation": {
        "tools": [
            {"name": "Google Translate", "url": "https://translate.google.com/", "desc": "Translation"},
            {"name": "DeepL", "url": "https://www.deepl.com/", "desc": "AI translation"},
            {"name": "Yandex Translate", "url": "https://translate.yandex.com/", "desc": "Translation"},
        ]
    },
    "metadata": {
        "tools": [
            {"name": "ExifTool", "url": "https://exiftool.org/", "desc": "Metadata reader"},
            {"name": "FOCA", "url": "https://github.com/ElevenPaths/FOCA", "desc": "Metadata extraction"},
            {"name": "Metagoofil", "url": "https://github.com/laramies/metagoofil", "desc": "Doc metadata extraction"},
            {"name": "Jeffrey EXIF", "url": "http://exif.regex.info/", "desc": "Online EXIF viewer"},
        ]
    },
    "mobile_emulation": {
        "tools": [
            {"name": "Appetize.io", "url": "https://appetize.io/", "desc": "Mobile app emulator"},
            {"name": "BrowserStack", "url": "https://www.browserstack.com/", "desc": "Cross-browser testing"},
            {"name": "Android Studio", "url": "https://developer.android.com/studio", "desc": "Android emulator"},
            {"name": "Genymotion", "url": "https://www.genymotion.com/", "desc": "Android emulation"},
        ]
    },
    "terrorism": {
        "tools": [
            {"name": "START GTD", "url": "https://www.start.umd.edu/gtd/", "desc": "Global terrorism database"},
            {"name": "TRAC", "url": "https://www.trackingterrorism.org/", "desc": "Terrorism research"},
            {"name": "SITE Intel", "url": "https://ent.siteintelgroup.com/", "desc": "Terrorism monitoring"},
        ]
    },
    "dark_web": {
        "tools": [
            {"name": "Ahmia", "url": "https://ahmia.fi/", "desc": "Tor search engine"},
            {"name": "OnionScan", "url": "https://github.com/s-rah/onionscan", "desc": "Dark web scanner"},
            {"name": "Torch", "url": "http://xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygthi7d6rplyvk3noyd.onion/", "desc": "Tor search"},
            {"name": "DarkSearch", "url": "https://darksearch.io/", "desc": "Dark web search API"},
            {"name": "IntelX", "url": "https://intelx.io/", "desc": "Intelligence search"},
        ]
    },
    "digital_currency": {
        "tools": [
            {"name": "Blockchain Explorer", "url": "https://www.blockchain.com/explorer", "desc": "Bitcoin explorer"},
            {"name": "Etherscan", "url": "https://etherscan.io/", "desc": "Ethereum explorer"},
            {"name": "Chainalysis", "url": "https://www.chainalysis.com/", "desc": "Blockchain analysis"},
            {"name": "WalletExplorer", "url": "https://www.walletexplorer.com/", "desc": "Bitcoin wallet tracker"},
            {"name": "BitRef", "url": "https://bitref.com/", "desc": "Bitcoin address lookup"},
        ]
    },
    "classifieds": {
        "tools": [
            {"name": "Craigslist", "url": "https://www.craigslist.org/", "desc": "Classifieds search"},
            {"name": "SearchTempest", "url": "https://www.searchtempest.com/", "desc": "Craigslist aggregator"},
            {"name": "Facebook Marketplace", "url": "https://www.facebook.com/marketplace/", "desc": "FB marketplace"},
            {"name": "OfferUp", "url": "https://offerup.com/", "desc": "Local marketplace"},
        ]
    },
    "encoding_decoding": {
        "tools": [
            {"name": "CyberChef", "url": "https://gchq.github.io/CyberChef/", "desc": "Data encoding/decoding swiss army knife"},
            {"name": "dCode", "url": "https://www.dcode.fr/en", "desc": "Cipher/code solver"},
            {"name": "Base64", "url": "https://www.base64decode.org/", "desc": "Base64 codec"},
            {"name": "URL Decoder", "url": "https://www.urldecoder.io/", "desc": "URL encoding"},
        ]
    },
    "ai_tools": {
        "tools": [
            {"name": "Dolphin Mistral 24B (OpenRouter)", "url": "https://openrouter.ai/", "desc": "Free uncensored AI via OpenRouter — primary OSINT analyst"},
            {"name": "Arcee Trinity Large (OpenRouter)", "url": "https://openrouter.ai/", "desc": "Free fallback AI model via OpenRouter"},
            {"name": "Serper (Google Search API)", "url": "https://serper.dev/", "desc": "Real-time Google search results API — powers AI dork queries"},
            {"name": "SearXNG (Self-Hosted)", "url": "https://github.com/searxng/searxng", "desc": "Free self-hosted metasearch engine — fallback for Serper"},
            {"name": "ChatGPT", "url": "https://chat.openai.com/", "desc": "AI assistant for analysis"},
            {"name": "Claude", "url": "https://claude.ai/", "desc": "AI analysis assistant"},
            {"name": "Perplexity", "url": "https://www.perplexity.ai/", "desc": "AI search engine"},
            {"name": "Gemini", "url": "https://gemini.google.com/", "desc": "Google AI"},
            {"name": "Hugging Face", "url": "https://huggingface.co/", "desc": "ML models/tools"},
        ]
    },
    "malware_analysis": {
        "tools": [
            {"name": "VirusTotal", "url": "https://www.virustotal.com/", "desc": "File/URL scanner"},
            {"name": "Any.run", "url": "https://any.run/", "desc": "Interactive sandbox"},
            {"name": "Hybrid Analysis", "url": "https://www.hybrid-analysis.com/", "desc": "Malware analysis"},
            {"name": "MalwareBazaar", "url": "https://bazaar.abuse.ch/", "desc": "Malware samples"},
            {"name": "URLhaus", "url": "https://urlhaus.abuse.ch/", "desc": "Malicious URL tracker"},
            {"name": "Joe Sandbox", "url": "https://www.joesandbox.com/", "desc": "Deep malware analysis"},
        ]
    },
    "exploits_advisories": {
        "tools": [
            {"name": "CVE Details", "url": "https://www.cvedetails.com/", "desc": "Vulnerability database"},
            {"name": "NVD", "url": "https://nvd.nist.gov/", "desc": "National vulnerability DB"},
            {"name": "Exploit-DB", "url": "https://www.exploit-db.com/", "desc": "Exploit archive"},
            {"name": "PacketStorm", "url": "https://packetstormsecurity.com/", "desc": "Security tools/exploits"},
            {"name": "Vulners", "url": "https://vulners.com/", "desc": "Vulnerability search"},
        ]
    },
    "threat_intelligence": {
        "tools": [
            {"name": "AlienVault OTX", "url": "https://otx.alienvault.com/", "desc": "Open threat exchange"},
            {"name": "MITRE ATT&CK", "url": "https://attack.mitre.org/", "desc": "Attack framework"},
            {"name": "ThreatCrowd", "url": "https://www.threatcrowd.org/", "desc": "Threat search engine"},
            {"name": "VirusTotal", "url": "https://www.virustotal.com/", "desc": "Multi-AV scanner"},
            {"name": "Pulsedive", "url": "https://pulsedive.com/", "desc": "Threat intelligence"},
            {"name": "ThreatFox", "url": "https://threatfox.abuse.ch/", "desc": "IOC sharing"},
        ]
    },
    "opsec": {
        "tools": [
            {"name": "Tor Browser", "url": "https://www.torproject.org/", "desc": "Anonymous browsing"},
            {"name": "Tails", "url": "https://tails.net/", "desc": "Amnesic live OS"},
            {"name": "Whonix", "url": "https://www.whonix.org/", "desc": "Anonymous OS"},
            {"name": "ProtonVPN", "url": "https://protonvpn.com/", "desc": "Secure VPN"},
            {"name": "ProtonMail", "url": "https://proton.me/mail", "desc": "Encrypted email"},
            {"name": "VeraCrypt", "url": "https://veracrypt.fr/", "desc": "Disk encryption"},
        ]
    },
    "documentation_evidence": {
        "tools": [
            {"name": "Hunchly", "url": "https://www.hunch.ly/", "desc": "Web capture for investigations"},
            {"name": "Maltego", "url": "https://www.maltego.com/", "desc": "Visual link analysis"},
            {"name": "KeepSafe PDF", "url": "https://smallpdf.com/", "desc": "PDF tools"},
            {"name": "Archive.today", "url": "https://archive.ph/", "desc": "Page archiving"},
            {"name": "HTTrack", "url": "https://www.httrack.com/", "desc": "Website copier"},
        ]
    },
    "training": {
        "tools": [
            {"name": "OSINT Dojo", "url": "https://www.yourfirstosint.com/", "desc": "OSINT training"},
            {"name": "TryHackMe", "url": "https://tryhackme.com/", "desc": "Cybersecurity training"},
            {"name": "HackTheBox", "url": "https://www.hackthebox.com/", "desc": "Pentesting labs"},
            {"name": "Trace Labs", "url": "https://www.tracelabs.org/", "desc": "OSINT CTF events"},
            {"name": "Cyber Defenders", "url": "https://cyberdefenders.org/", "desc": "Blue team training"},
            {"name": "SANS OSINT", "url": "https://www.sans.org/cyber-security-courses/open-source-intelligence-gathering/", "desc": "SANS OSINT course"},
        ]
    },
}


# =============================================================================
# OSINT Engine - Active Intelligence Gathering
# =============================================================================


class TTLCache:
    """Simple async-safe TTL cache"""
    def __init__(self, ttl: int = 300):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        if key in self._cache:
            ts, value = self._cache[key]
            if time.time() - ts < self._ttl:
                return value
            del self._cache[key]
        return None

    def set(self, key: str, value: Any):
        self._cache[key] = (time.time(), value)

    def clear(self):
        self._cache.clear()

def validate_input(input_type: str):
    """Decorator for input validation"""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(self, target: str, *args, **kwargs):
            target = target.strip()
            if not target:
                return OSINTResult(
                    category=func.__name__, query=target,
                    success=False, error="Empty input"
                )
            if input_type == 'email':
                if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', target):
                    return OSINTResult(
                        category=func.__name__, query=target,
                        success=False, error="Invalid email format"
                    )
            elif input_type == 'ip':
                try:
                    import ipaddress
                    ipaddress.ip_address(target)
                except ValueError:
                    return OSINTResult(
                        category=func.__name__, query=target,
                        success=False, error="Invalid IP address"
                    )
            elif input_type == 'domain':
                if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', target):
                    return OSINTResult(
                        category=func.__name__, query=target,
                        success=False, error="Invalid domain format"
                    )
            return await func(self, target, *args, **kwargs)
        return wrapper
    return decorator

class OSINTEngine:

    """
    Comprehensive OSINT Engine with 30+ intelligence categories.
    Uses only aiohttp + stdlib for all operations.
    """

    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    ]

    HEADERS = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }

    PLATFORM_404_SIGNATURES = {
        'instagram.com': {'method': 'get', 'not_found': ['"HttpErrorPage"', 'Page Not Found']},
        'github.com': {'method': 'head', 'status_404': True},
        'twitter.com': {'method': 'get', 'not_found': ['This account doesn', 'page doesn']},
        'x.com': {'method': 'get', 'not_found': ['This account doesn', 'page doesn']},
        'reddit.com': {'method': 'get_json', 'check': lambda d: 'error' not in str(d).lower()},
        'tiktok.com': {'method': 'get', 'not_found': ["Couldn't find this account"]},
        'linkedin.com': {'method': 'head', 'status_404': True},
        'facebook.com': {'method': 'get', 'not_found': ['page isn', 'content isn']},
    }

    @property
    def _random_headers(self) -> Dict[str, str]:
        return {
            **self.HEADERS,
            'User-Agent': random.choice(self.USER_AGENTS),
        }

    def __init__(self, verify_ssl: bool = True, max_concurrent: int = 10, proxy: str = None, tor: bool = False):
        self.results: List[OSINTResult] = []
        self.session: Optional[aiohttp.ClientSession] = None
        self._owns_session = False
        self.verify_ssl = verify_ssl
        self._proxy = proxy
        if tor:
            self._proxy = 'socks5://127.0.0.1:9050'
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._request_delay = 0.1
        self._last_request_time: Dict[str, float] = {}
        self._cache = TTLCache(ttl=300)

    async def _ensure_session(self):
        """Lazily fetch shared session"""
        if self.session is None or self.session.closed:
            from shared import SessionManager
            self.session = await SessionManager.get().session()
            self._owns_session = False

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def close(self):
        """No-op because session is shared"""
        pass

    async def __aexit__(self, *args):
        pass

    def __del__(self):
        pass

    # ---- Helper Methods ----

    async def _fetch(self, url: str, **kwargs) -> Optional[str]:
        from shared import SessionManager
        session_manager = SessionManager.get()
        return await session_manager.fetch(url, ssl=self.verify_ssl, proxy=self._proxy, **kwargs)
    async def _rate_limited_fetch(self, url: str, **kwargs) -> Optional[str]:
        host = urlparse(url).netloc
        async with self._semaphore:
            now = asyncio.get_running_loop().time()
            last = self._last_request_time.get(host, 0)
            wait = max(0, self._request_delay - (now - last))
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_time[host] = asyncio.get_running_loop().time()
            return await self._fetch(url, **kwargs)

    async def _fetch_with_retry(self, url: str, max_retries: int = 2, **kwargs) -> Optional[str]:
        from shared import SessionManager
        session_manager = SessionManager.get()
        for attempt in range(max_retries + 1):
            try:
                async with self._semaphore:
                    session = await session_manager.session()
                    async with session.get(url, ssl=self.verify_ssl, proxy=self._proxy, **kwargs) as r:
                        if r.status == 200:
                            return await r.text()
                        elif r.status == 429:
                            retry_after = int(r.headers.get('Retry-After', 2 ** attempt))
                            logger.info(f"Rate limited on {url}, waiting {retry_after}s")
                            await asyncio.sleep(retry_after)
                            continue
                        elif r.status >= 500:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        else:
                            return None
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                logger.debug(f"All retries failed for {url}: {e}")
            except Exception:
                break
        return None

    async def _fetch_json(self, url: str, use_cache: bool = True, **kwargs) -> Optional[dict]:
        from shared import SessionManager
        session_manager = SessionManager.get()

        if use_cache:
            cached = self._cache.get(url)
            if cached is not None:
                return cached
                
        try:
            session = await session_manager.session()
            async with session.get(url, ssl=self.verify_ssl, proxy=self._proxy, **kwargs) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    if use_cache and data:
                        self._cache.set(url, data)
                    return data
        except Exception:
            pass
        return None

    async def _check_url(self, url: str) -> Tuple[bool, int]:
        from shared import SessionManager
        session_manager = SessionManager.get()
        try:
            session = await session_manager.session()
            async with session.head(
                url, ssl=self.verify_ssl, proxy=self._proxy, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                return r.status < 400, r.status
        except Exception:
            return False, 0

    def _dns_lookup(self, domain: str, record_type: str = 'A') -> List[str]:
        results = []
        if not re.match(r'^[a-zA-Z0-9._-]+$', domain):
            logger.warning(f"Invalid domain chars rejected: {domain}")
            return results
        try:
            if record_type == 'A':
                results = list({r[4][0] for r in socket.getaddrinfo(domain, None, socket.AF_INET)})
            elif record_type == 'AAAA':
                results = list({r[4][0] for r in socket.getaddrinfo(domain, None, socket.AF_INET6)})
            elif record_type in ('MX', 'NS', 'TXT'):
                import subprocess
                r = subprocess.run(
                    ['nslookup', f'-type={record_type}', '--', domain],
                    capture_output=True, text=True, timeout=10,
                    shell=False
                )
                if record_type == 'MX':
                    results = re.findall(r'mail exchanger = (.+)', r.stdout)
                elif record_type == 'NS':
                    results = re.findall(r'nameserver = (.+)', r.stdout)
                elif record_type == 'TXT':
                    results = re.findall(r'"(.+?)"', r.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
            logger.debug(f"DNS lookup failed for {domain}/{record_type}: {e}")
        except Exception as e:
            logger.debug(f"DNS lookup error: {e}")
        return list(set(results))

    def _get_ssl_info(self, domain: str) -> Dict:
        info = {}
        try:
            ctx = ssl.create_default_context()
            with ctx.wrap_socket(socket.socket(), server_hostname=domain) as s:
                s.settimeout(10)
                s.connect((domain, 443))
                cert = s.getpeercert()
                info['subject'] = dict(x[0] for x in cert.get('subject', []))
                info['issuer'] = dict(x[0] for x in cert.get('issuer', []))
                info['serial'] = cert.get('serialNumber')
                info['not_before'] = cert.get('notBefore')
                info['not_after'] = cert.get('notAfter')
                info['san'] = [x[1] for x in cert.get('subjectAltName', [])]
                info['version'] = cert.get('version')
        except Exception as e:
            info['error'] = str(e)
        return info

    # =========================================================================
    # 1. DOMAIN RECON
    # =========================================================================

    @validate_input('domain')
    async def domain_recon(self, domain: str) -> OSINTResult:
        """Full domain reconnaissance"""
        await self._ensure_session()
        result = OSINTResult(category="Domain Recon", query=domain)
        domain = domain.replace('https://', '').replace('http://', '').strip('/')

        # DNS Records and SSL via Thread Executor
        loop = asyncio.get_running_loop()
        dns_tasks = {
            'dns_a': loop.run_in_executor(None, self._dns_lookup, domain, 'A'),
            'dns_aaaa': loop.run_in_executor(None, self._dns_lookup, domain, 'AAAA'),
            'dns_mx': loop.run_in_executor(None, self._dns_lookup, domain, 'MX'),
            'dns_ns': loop.run_in_executor(None, self._dns_lookup, domain, 'NS'),
            'dns_txt': loop.run_in_executor(None, self._dns_lookup, domain, 'TXT'),
            'ssl_cert': loop.run_in_executor(None, self._get_ssl_info, domain),
        }
        dns_results = await asyncio.gather(*dns_tasks.values(), return_exceptions=True)
        for key, value in zip(dns_tasks.keys(), dns_results):
            result.data[key] = value if not isinstance(value, Exception) else []

        # HTTP Headers
        try:
            async with self.session.get(f'https://{domain}', ssl=False) as r:
                result.data['http_status'] = r.status
                result.data['http_headers'] = dict(r.headers)
                result.data['server'] = r.headers.get('Server', 'Unknown')
                result.data['technologies'] = self._detect_tech(dict(r.headers))
        except Exception:
            pass

        # Subdomains via crt.sh
        crt_data = await self._fetch_json(f'https://crt.sh/?q=%.{domain}&output=json')
        if crt_data and isinstance(crt_data, list):
            subdomains = set()
            for entry in crt_data:
                name = entry.get('name_value', '')
                for n in name.split('\n'):
                    n = n.strip().lower()
                    if n.endswith(domain) and '*' not in n:
                        subdomains.add(n)
            result.data['subdomains'] = sorted(subdomains)
            result.data['subdomain_count'] = len(subdomains)

        # IP Geolocation
        for ip in result.data.get('dns_a', [])[:1]:
            geo = await self._fetch_json(f'http://ip-api.com/json/{ip}')
            if geo:
                result.data['geolocation'] = geo

        # Wayback availability
        wb = await self._fetch_json(f'https://archive.org/wayback/available?url={domain}')
        if wb and wb.get('archived_snapshots'):
            result.data['wayback'] = wb['archived_snapshots']

        result.sources = [f"DNS", f"SSL", f"crt.sh", "ip-api.com", "archive.org"]
        self.results.append(result)
        return result

    def _detect_tech(self, headers: Dict) -> List[str]:
        tech = []
        h_str = json.dumps(headers, default=str).lower()

        signatures = {
            'nginx': 'Nginx', 'apache': 'Apache', 'cloudflare': 'Cloudflare',
            'x-aspnet': 'ASP.NET', 'express': 'Express.js', 'php': 'PHP',
            'next.js': 'Next.js', 'wordpress': 'WordPress', 'drupal': 'Drupal',
            'aws': 'AWS', 'varnish': 'Varnish', 'litespeed': 'LiteSpeed',
            'openresty': 'OpenResty', 'gunicorn': 'Gunicorn', 'uvicorn': 'Uvicorn',
        }
        for sig, name in signatures.items():
            if sig in h_str:
                tech.append(name)

        powered_by = headers.get('X-Powered-By', '')
        if powered_by:
            tech.append(f"X-Powered-By: {powered_by}")

        encoding = headers.get('Content-Encoding', '').lower()
        if 'gzip' in encoding:
            tech.append('Gzip')
        if 'br' in encoding:
            tech.append('Brotli')

        return list(set(tech))

    # =========================================================================
    # 2. EMAIL OSINT (Enhanced - Live Platform Verification)
    # =========================================================================

    @validate_input('email')
    async def email_osint(self, email: str) -> OSINTResult:
        """Enhanced email intelligence with live platform verification"""
        result = OSINTResult(category="Email OSINT", query=email)

        # Validate format
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        result.data['valid_format'] = bool(re.match(pattern, email))

        local, domain = email.split('@') if '@' in email else (email, '')
        result.data['local_part'] = local
        result.data['domain'] = domain

        # Domain MX records
        result.data['mx_records'] = self._dns_lookup(domain, 'MX')
        result.data['domain_exists'] = len(result.data['mx_records']) > 0

        # Detect email provider
        provider_map = {
            'gmail.com': 'Google/Gmail', 'googlemail.com': 'Google/Gmail',
            'outlook.com': 'Microsoft/Outlook', 'hotmail.com': 'Microsoft/Hotmail',
            'live.com': 'Microsoft/Live', 'yahoo.com': 'Yahoo', 'yahoo.co.in': 'Yahoo India',
            'protonmail.com': 'ProtonMail', 'proton.me': 'ProtonMail',
            'icloud.com': 'Apple/iCloud', 'me.com': 'Apple',
            'aol.com': 'AOL', 'zoho.com': 'Zoho', 'yandex.com': 'Yandex',
            'mail.com': 'Mail.com', 'gmx.com': 'GMX', 'tutanota.com': 'Tutanota',
        }
        result.data['email_provider'] = provider_map.get(domain.lower(), f'Custom ({domain})')

        # --- Gravatar Profile (JSON API - free, no key) ---
        email_hash = hashlib.md5(email.lower().strip().encode()).hexdigest()
        result.data['gravatar_url'] = f"https://www.gravatar.com/avatar/{email_hash}"
        grav_ok, _ = await self._check_url(f"https://www.gravatar.com/avatar/{email_hash}?d=404")
        result.data['has_gravatar'] = grav_ok
        if grav_ok:
            grav_profile = await self._fetch_json(f"https://www.gravatar.com/{email_hash}.json")
            if grav_profile and 'entry' in grav_profile:
                entry = grav_profile['entry'][0]
                result.data['gravatar_profile'] = {
                    'display_name': entry.get('displayName', 'N/A'),
                    'about': entry.get('aboutMe', 'N/A'),
                    'location': entry.get('currentLocation', 'N/A'),
                    'urls': [u.get('value') for u in entry.get('urls', [])],
                    'accounts': {a.get('shortname'): a.get('url') for a in entry.get('accounts', [])},
                    'photos': [p.get('value') for p in entry.get('photos', [])],
                }

        # --- EmailRep.io API (free, no key required for basic lookups) ---
        emailrep = await self._api_emailrep(email)
        if emailrep:
            result.data['email_reputation'] = emailrep

        # --- Live Platform Verification (actually check if accounts exist) ---
        platforms_to_check = {
            'GitHub': f'https://api.github.com/users/{local}',
            'Twitter/X': f'https://x.com/{local}',
            'Instagram': f'https://www.instagram.com/{local}/',
            'Facebook': f'https://www.facebook.com/{local}',
            'Reddit': f'https://www.reddit.com/user/{local}/about.json',
            'LinkedIn': f'https://www.linkedin.com/in/{local}',
            'Pinterest': f'https://www.pinterest.com/{local}/',
            'TikTok': f'https://www.tiktok.com/@{local}',
            'YouTube': f'https://www.youtube.com/@{local}',
            'Medium': f'https://medium.com/@{local}',
            'DevTo': f'https://dev.to/{local}',
            'Keybase': f'https://keybase.io/{local}',
            'Dribbble': f'https://dribbble.com/{local}',
            'Behance': f'https://www.behance.net/{local}',
            'GitLab': f'https://gitlab.com/{local}',
            'Bitbucket': f'https://bitbucket.org/{local}/',
            'HackerRank': f'https://hackerrank.com/{local}',
            'LeetCode': f'https://leetcode.com/{local}',
            'Mastodon': f'https://mastodon.social/@{local}',
            'Twitch': f'https://www.twitch.tv/{local}',
            'Spotify': f'https://open.spotify.com/user/{local}',
            'SoundCloud': f'https://soundcloud.com/{local}',
            'Vimeo': f'https://vimeo.com/{local}',
            'Patreon': f'https://www.patreon.com/{local}',
        }

        # Run live checks in parallel
        verified_profiles = {}
        not_found = []
        check_tasks = []
        platform_names = list(platforms_to_check.keys())
        for name, url in platforms_to_check.items():
            check_tasks.append(self._check_url(url))

        checks = await asyncio.gather(*check_tasks, return_exceptions=True)
        for i, name in enumerate(platform_names):
            if i < len(checks) and not isinstance(checks[i], Exception):
                exists, status = checks[i]
                if exists:
                    verified_profiles[name] = platforms_to_check[name]
                else:
                    not_found.append(name)

        result.data['verified_profiles'] = verified_profiles
        result.data['verified_count'] = len(verified_profiles)
        result.data['platforms_checked'] = len(platforms_to_check)
        result.data['not_found_on'] = not_found

        # --- GitHub API enrichment (free, 60 req/hr) ---
        if 'GitHub' in verified_profiles:
            gh_data = await self._api_github_user(local)
            if gh_data:
                result.data['github_profile'] = gh_data

        # --- Reddit API enrichment (free, public) ---
        reddit_data = await self._api_reddit_user(local)
        if reddit_data:
            result.data['reddit_profile'] = reddit_data

        result.sources = ["DNS", "Gravatar API", "EmailRep.io", "Live HTTP Checks", "GitHub API", "Reddit API"]
        self.results.append(result)
        return result

    # =========================================================================
    # 3. USERNAME OSINT
    # =========================================================================

    async def username_osint(self, username: str, check_live: bool = True) -> OSINTResult:
        """Search username across 35+ platforms"""
        result = OSINTResult(category="Username OSINT", query=username)

        platforms = OSINT_RESOURCES['social_networks']['platforms_to_check']
        profile_urls = {
            urlparse(p).netloc.replace('www.', ''): p.format(username)
            for p in platforms
        }
        result.data['generated_urls'] = profile_urls

        if check_live:
            found = {}
            not_found = []
            diagnostics = {'timeouts': 0, 'blocked': 0, 'errors': 0, 'rate_limited': 0}

            items = list(profile_urls.items())
            tasks = [self._check_profile_throttled(platform, url) for platform, url in items]
            checks = await asyncio.gather(*tasks, return_exceptions=True)

            for (platform, url), check_result in zip(items, checks):
                if isinstance(check_result, Exception):
                    diagnostics['errors'] += 1
                    continue
                exists, status, reason = check_result
                if exists:
                    found[platform] = url
                else:
                    not_found.append(platform)
                    if reason == 'timeout': diagnostics['timeouts'] += 1
                    elif reason == 'blocked': diagnostics['blocked'] += 1
                    elif reason == 'rate_limited': diagnostics['rate_limited'] += 1
                    elif reason == 'error' or reason == 'connection_error': diagnostics['errors'] += 1

            result.data['found_profiles'] = found
            result.data['not_found'] = not_found
            result.data['found_count'] = len(found)
            result.data['checked_count'] = len(profile_urls)
            result.data['check_diagnostics'] = diagnostics

        result.sources = ["HTTP Status Check"]
        self.results.append(result)
        return result

    async def sherlock_osint(self, username: str, timeout: int = 30) -> OSINTResult:
        """Enhanced username search using Sherlock"""
        result = OSINTResult(category="Sherlock OSINT", query=username)
        
        found = {}
        not_found = []
        
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Run Sherlock CLI securely
                process = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "sherlock_project", username, 
                    "--csv", "--folderoutput", temp_dir, "--timeout", str(timeout), "--no-color",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # We can wait for it to complete (or time out)
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout * 20)
                except asyncio.TimeoutError:
                    process.kill()
                    result.success = False
                    result.error = "Sherlock process timed out."
                    return result
                
                # Check for the expected CSV file
                csv_file = os.path.join(temp_dir, f"{username}.csv")
                if os.path.exists(csv_file):
                    with open(csv_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            site = row.get('name', '')
                            url = row.get('url_user', '')
                            status = row.get('exists', '')
                            
                            if status == 'Claimed' or status.lower() == 'yes':
                                found[site] = url
                            else:
                                not_found.append(site)
                elif process.returncode != 0 and not found:
                    result.success = False
                    result.error = f"Sherlock failed with code {process.returncode}: {stderr.decode('utf-8', errors='ignore')}"
                    return result
                    
            except Exception as e:
                result.success = False
                result.error = str(e)
                return result

        result.data['found_profiles'] = found
        result.data['not_found'] = not_found
        result.data['found_count'] = len(found)
        result.data['checked_count'] = len(found) + len(not_found)
        result.sources = ["Sherlock (300+ platforms)"]
        self.results.append(result)
        return result

    async def _check_profile_throttled(self, platform: str, url: str) -> Tuple[bool, int, str]:
        async with self._semaphore:
            await asyncio.sleep(0.05)
            return await self._check_profile(platform, url)

    async def _check_profile(self, platform: str, url: str) -> Tuple[bool, int, str]:
        """Check if a profile exists. Returns (exists, status_code, reason)."""
        await self._ensure_session()
        try:
            domain = urlparse(url).netloc.replace('www.', '')
            sig = self.PLATFORM_404_SIGNATURES.get(domain, {})
            method = sig.get('method', 'head')

            if method == 'head' or sig.get('status_404'):
                async with self.session.head(
                    url, ssl=self.verify_ssl, proxy=self._proxy, allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status == 404:
                        return False, 404, 'not_found'
                    if r.status == 403:
                        return False, 403, 'blocked'
                    if r.status == 429:
                        return False, 429, 'rate_limited'
                    if r.status >= 400:
                        return False, r.status, f'http_{r.status}'
                    if not sig:
                        return True, r.status, 'found'
                    return r.status < 400, r.status, 'found' if r.status < 400 else 'not_found'

            elif method in ('get', 'get_json'):
                async with self.session.get(
                    url, ssl=self.verify_ssl, proxy=self._proxy, allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as r:
                    if r.status >= 400:
                        return False, r.status, 'blocked' if r.status in (403, 429) else 'not_found'
                    text = await r.text()
                    not_found_sigs = sig.get('not_found', [])
                    for nf in not_found_sigs:
                        if nf.lower() in text.lower():
                            return False, r.status, 'not_found'
                    return True, r.status, 'found'

        except asyncio.TimeoutError:
            return False, 0, 'timeout'
        except aiohttp.ClientError:
            return False, 0, 'connection_error'
        except Exception:
            return False, 0, 'error'
        return False, 0, 'unknown'

    # =========================================================================
    # 4. IP / MAC ADDRESS OSINT
    # =========================================================================

    async def ip_osint(self, ip: str) -> OSINTResult:
        """IP address intelligence"""
        result = OSINTResult(category="IP OSINT", query=ip)

        # Validate IP
        try:
            addr = ipaddress.ip_address(ip)
            result.data['version'] = 'IPv6' if addr.version == 6 else 'IPv4'
            result.data['is_private'] = addr.is_private
            result.data['is_loopback'] = addr.is_loopback
            result.data['is_multicast'] = addr.is_multicast
        except ValueError:
            result.data['valid'] = False
            result.error = "Invalid IP address"
            result.success = False
            return result

        # Geolocation via ip-api
        geo = await self._fetch_json(f'http://ip-api.com/json/{ip}?fields=66846719')
        if geo:
            result.data['geolocation'] = geo

        # Reverse DNS
        try:
            hostname = socket.gethostbyaddr(ip)
            result.data['reverse_dns'] = hostname[0]
            result.data['aliases'] = hostname[1]
        except Exception:
            result.data['reverse_dns'] = None

        # Abuse check tools
        result.data['check_tools'] = {
            'AbuseIPDB': f'https://www.abuseipdb.com/check/{ip}',
            'Shodan': f'https://www.shodan.io/host/{ip}',
            'Censys': f'https://search.censys.io/hosts/{ip}',
            'GreyNoise': f'https://viz.greynoise.io/ip/{ip}',
            'VirusTotal': f'https://www.virustotal.com/gui/ip-address/{ip}',
        }

        result.sources = ["ip-api.com", "Reverse DNS"]
        self.results.append(result)
        return result

    async def mac_lookup(self, mac: str) -> OSINTResult:
        """MAC address vendor lookup"""
        result = OSINTResult(category="MAC Lookup", query=mac)
        clean = mac.replace(':', '').replace('-', '').replace('.', '').upper()[:6]
        result.data['oui'] = clean

        data = await self._fetch_json(f'https://api.macvendors.com/{clean}')
        if isinstance(data, str):
            result.data['vendor'] = data
        else:
            text = await self._fetch(f'https://api.macvendors.com/{clean}')
            result.data['vendor'] = text.strip() if text else 'Unknown'

        result.sources = ["macvendors.com"]
        self.results.append(result)
        return result

    # =========================================================================
    # 5. WEB PAGE OSINT
    # =========================================================================

    async def page_osint(self, url: str) -> OSINTResult:
        """Extract intelligence from a web page"""
        result = OSINTResult(category="Web Page OSINT", query=url)

        html = await self._fetch(url)
        if not html:
            result.error = "Could not fetch page"
            result.success = False
            return result

        # Extract emails
        emails = set(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', html))
        result.data['emails'] = sorted(emails)

        # Extract phone numbers
        PHONE_PATTERNS = [
            r'\+?1?\s*\(?[2-9]\d{2}\)?[\s.-]\d{3}[\s.-]\d{4}',
            r'\+[1-9]\d{0,2}[\s.-]?\(?\d{1,4}\)?[\s.-]?\d{2,4}[\s.-]?\d{3,4}',
            r'\+\d{10,15}',
            r'(?:tel|phone|mobile|fax)[\s:]+[\+]?[\d\s\-\(\)]{10,15}',
        ]
        phones = set()
        for pattern in PHONE_PATTERNS:
            phones.update(re.findall(pattern, html, re.I))
        cleaned_phones = sorted(
            p.strip() for p in phones
            if len(re.sub(r'[^\d]', '', p)) >= 10
        )
        result.data['phone_numbers'] = cleaned_phones

        # NumVerify enrichment for extracted phone numbers (up to 5)
        if cleaned_phones:
            numverify_results = []
            for p in cleaned_phones[:5]:
                nv = await self._api_numverify(re.sub(r'[^\d+]', '', p))
                if nv:
                    numverify_results.append({**nv, 'original': p})
            if numverify_results:
                result.data['phone_numverify'] = numverify_results

        # Extract social media links
        social = set()
        social_patterns = [
            r'https?://(?:www\.)?(?:facebook|fb)\.com/[^\s"\'<>]+',
            r'https?://(?:www\.)?twitter\.com/[^\s"\'<>]+',
            r'https?://(?:www\.)?instagram\.com/[^\s"\'<>]+',
            r'https?://(?:www\.)?linkedin\.com/[^\s"\'<>]+',
            r'https?://(?:www\.)?youtube\.com/[^\s"\'<>]+',
            r'https?://(?:www\.)?tiktok\.com/[^\s"\'<>]+',
            r'https?://(?:www\.)?github\.com/[^\s"\'<>]+',
            r'https?://t\.me/[^\s"\'<>]+',
        ]
        for p in social_patterns:
            social.update(re.findall(p, html, re.I))
        result.data['social_links'] = sorted(social)

        # Extract all domains linked
        domains = set(re.findall(r'https?://([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', html))
        result.data['linked_domains'] = sorted(domains)

        # Page metadata
        title = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        result.data['title'] = title.group(1).strip() if title else None

        # Meta tags
        metas = {}
        for m in re.finditer(r'<meta\s+(?:name|property)=["\']([^"\']+)["\']\s+content=["\']([^"\']*)["\']', html, re.I):
            metas[m.group(1)] = m.group(2)
        result.data['meta_tags'] = metas

        result.sources = ["Direct HTTP fetch"]
        self.results.append(result)
        return result

    # =========================================================================
    # 6. PHONE NUMBER OSINT
    # =========================================================================

    async def phone_osint(self, phone: str) -> OSINTResult:
        """Phone number intelligence with NumVerify API enrichment"""
        result = OSINTResult(category="Phone OSINT", query=phone)
        clean = re.sub(r'[^\d+]', '', phone)
        result.data['cleaned'] = clean
        result.data['digits'] = len(clean.replace('+', ''))

        # Country code detection (fallback)
        country_codes = {
            '1': 'US/Canada', '44': 'UK', '91': 'India', '86': 'China',
            '81': 'Japan', '49': 'Germany', '33': 'France', '39': 'Italy',
            '7': 'Russia', '55': 'Brazil', '61': 'Australia', '82': 'South Korea',
            '34': 'Spain', '31': 'Netherlands', '46': 'Sweden', '47': 'Norway',
            '90': 'Turkey', '966': 'Saudi Arabia', '971': 'UAE', '92': 'Pakistan',
            '880': 'Bangladesh', '234': 'Nigeria', '254': 'Kenya', '27': 'South Africa',
        }
        num = clean.lstrip('+')
        for code, country in sorted(country_codes.items(), key=lambda x: -len(x[0])):
            if num.startswith(code):
                result.data['country_code'] = f'+{code}'
                result.data['country'] = country
                break

        # --- NumVerify API (live carrier, location, validation) ---
        numverify = await self._api_numverify(clean)
        if numverify:
            result.data['numverify'] = numverify
            # Override fallback data with API-verified data
            if numverify.get('valid'):
                result.data['valid'] = True
                if numverify.get('country_name'):
                    result.data['country'] = numverify['country_name']
                if numverify.get('country_prefix'):
                    result.data['country_code'] = numverify['country_prefix']
                if numverify.get('international_format'):
                    result.data['international_format'] = numverify['international_format']
                if numverify.get('local_format'):
                    result.data['local_format'] = numverify['local_format']
                if numverify.get('carrier'):
                    result.data['carrier'] = numverify['carrier']
                if numverify.get('line_type'):
                    result.data['line_type'] = numverify['line_type']
                if numverify.get('location'):
                    result.data['location'] = numverify['location']
            else:
                result.data['valid'] = False
        else:
            result.data['numverify'] = 'API unavailable or quota exceeded'

        result.data['lookup_tools'] = {
            'TrueCaller': f'https://www.truecaller.com/search/{"".join(filter(str.isdigit, phone))}',
            'Sync.me': f'https://sync.me/search/?number={clean}',
            'CallerID': f'https://calleridtest.com/lookup/{clean}',
            'NumLookup': f'https://www.numlookup.com/lookup/{clean}',
        }

        result.sources = ["Pattern Analysis", "NumVerify API"]
        self.results.append(result)
        return result

    # =========================================================================
    # 7. FREE API INTEGRATIONS
    # =========================================================================

    async def _api_emailrep(self, email: str) -> Optional[Dict]:
        """EmailRep.io - free email reputation (no API key needed for basic)"""
        await self._ensure_session()
        try:
            headers = {**self.HEADERS, 'Accept': 'application/json'}
            async with self.session.get(f'https://emailrep.io/{email}', headers=headers, ssl=self.verify_ssl, proxy=self._proxy) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    return {
                        'reputation': data.get('reputation', 'unknown'),
                        'suspicious': data.get('suspicious', False),
                        'references': data.get('references', 0),
                        'blacklisted': data.get('details', {}).get('blacklisted', False),
                        'malicious_activity': data.get('details', {}).get('malicious_activity', False),
                        'credential_leaked': data.get('details', {}).get('credentials_leaked', False),
                        'data_breach': data.get('details', {}).get('data_breach', False),
                        'first_seen': data.get('details', {}).get('first_seen', 'never'),
                        'last_seen': data.get('details', {}).get('last_seen', 'never'),
                        'domain_exists': data.get('details', {}).get('domain_exists', False),
                        'free_provider': data.get('details', {}).get('free_provider', False),
                        'disposable': data.get('details', {}).get('disposable', False),
                        'deliverable': data.get('details', {}).get('deliverable', False),
                        'spam': data.get('details', {}).get('spam', False),
                        'profiles': data.get('details', {}).get('profiles', []),
                    }
        except Exception as e:
            logger.debug(f"EmailRep API error: {e}")
        return None

    async def _api_github_user(self, username: str) -> Optional[Dict]:
        """GitHub public API - 60 req/hr without auth"""
        data = await self._fetch_json(f'https://api.github.com/users/{username}')
        if data and 'login' in data:
            repos = await self._fetch_json(f'https://api.github.com/users/{username}/repos?sort=updated&per_page=5')
            return {
                'username': data.get('login'),
                'name': data.get('name'),
                'bio': data.get('bio'),
                'company': data.get('company'),
                'location': data.get('location'),
                'blog': data.get('blog'),
                'twitter': data.get('twitter_username'),
                'public_repos': data.get('public_repos', 0),
                'public_gists': data.get('public_gists', 0),
                'followers': data.get('followers', 0),
                'following': data.get('following', 0),
                'created_at': data.get('created_at'),
                'updated_at': data.get('updated_at'),
                'avatar_url': data.get('avatar_url'),
                'profile_url': data.get('html_url'),
                'recent_repos': [
                    {'name': r.get('name'), 'description': r.get('description'),
                     'language': r.get('language'), 'stars': r.get('stargazers_count', 0),
                     'url': r.get('html_url')}
                    for r in (repos or [])[:5]
                ] if repos else [],
            }
        return None

    async def _api_reddit_user(self, username: str) -> Optional[Dict]:
        """Reddit public user JSON (no auth)"""
        headers = {**self.HEADERS, 'Accept': 'application/json'}
        data = await self._fetch_json(f'https://www.reddit.com/user/{username}/about.json', headers=headers)
        if data and 'data' in data:
            d = data['data']
            return {
                'username': d.get('name'),
                'total_karma': d.get('total_karma', 0),
                'link_karma': d.get('link_karma', 0),
                'comment_karma': d.get('comment_karma', 0),
                'created_utc': d.get('created_utc'),
                'has_verified_email': d.get('has_verified_email', False),
                'is_gold': d.get('is_gold', False),
                'is_mod': d.get('is_mod', False),
                'icon_img': d.get('icon_img'),
                'subreddit_name': d.get('subreddit', {}).get('display_name_prefixed'),
            }
        return None

    async def _api_numverify(self, phone: str) -> Optional[Dict]:
        """NumVerify API - phone number validation, carrier, location, line type"""
        api_key = os.environ.get('NUMVERIFY_API_KEY', '')
        if not api_key:
            logger.debug("NumVerify API key not configured")
            return None

        # Strip leading '+' for the API (it expects raw digits)
        number = phone.lstrip('+')
        url = f'http://apilayer.net/api/validate?access_key={api_key}&number={number}'

        try:
            data = await self._fetch_json(url, use_cache=True)
            if data and 'valid' in data:
                # Check for API error responses
                if 'error' in data and data['error']:
                    logger.debug(f"NumVerify API error: {data['error']}")
                    return None
                return {
                    'valid': data.get('valid', False),
                    'number': data.get('number'),
                    'local_format': data.get('local_format'),
                    'international_format': data.get('international_format'),
                    'country_prefix': data.get('country_prefix'),
                    'country_code': data.get('country_code'),
                    'country_name': data.get('country_name'),
                    'location': data.get('location'),
                    'carrier': data.get('carrier'),
                    'line_type': data.get('line_type'),
                }
            elif data and 'error' in data:
                err = data['error']
                logger.debug(f"NumVerify API error: {err.get('info', err)}")
        except Exception as e:
            logger.debug(f"NumVerify API error: {e}")
        return None

    async def _api_hackertarget(self, target: str, scan_type: str = 'hostsearch') -> Optional[List[str]]:
        """HackerTarget free API - DNS lookups, reverse IP, etc."""
        valid_types = ['hostsearch', 'reversedns', 'dnslookup', 'httpheaders', 'pagelinks', 'whois']
        if scan_type not in valid_types:
            scan_type = 'hostsearch'
        text = await self._fetch(f'https://api.hackertarget.com/{scan_type}/?q={target}')
        if text and 'error' not in text.lower() and 'API count' not in text:
            return [line.strip() for line in text.strip().split('\n') if line.strip()]
        return None

    async def _api_urlscan(self, target: str) -> Optional[Dict]:
        """URLScan.io - search for existing scans (free, no key for search)"""
        data = await self._fetch_json(f'https://urlscan.io/api/v1/search/?q=domain:{target}&size=5')
        if data and 'results' in data:
            return {
                'total_results': data.get('total', 0),
                'recent_scans': [
                    {
                        'url': r.get('page', {}).get('url'),
                        'domain': r.get('page', {}).get('domain'),
                        'ip': r.get('page', {}).get('ip'),
                        'country': r.get('page', {}).get('country'),
                        'server': r.get('page', {}).get('server'),
                        'title': r.get('page', {}).get('title'),
                        'scan_time': r.get('task', {}).get('time'),
                        'screenshot': r.get('screenshot'),
                    }
                    for r in data.get('results', [])[:5]
                ]
            }
        return None

    async def _api_shodan_internetdb(self, ip: str) -> Optional[Dict]:
        """Shodan InternetDB - free, no API key needed"""
        data = await self._fetch_json(f'https://internetdb.shodan.io/{ip}')
        if data and 'ip' in str(data):
            return {
                'ip': data.get('ip'),
                'hostnames': data.get('hostnames', []),
                'ports': data.get('ports', []),
                'cpes': data.get('cpes', []),
                'vulns': data.get('vulns', []),
                'tags': data.get('tags', []),
            }
        return None

    async def _api_virustotal_domain(self, domain: str) -> Optional[Dict]:
        """Check VirusTotal community info (limited without key)"""
        # Use the passive approach - check if domain resolves + urlscan
        results = {}
        # Use URLScan as free alternative
        urlscan_data = await self._api_urlscan(domain)
        if urlscan_data:
            results['urlscan'] = urlscan_data
        # Check ThreatCrowd (free, no key)
        tc_data = await self._fetch_json(f'https://www.threatcrowd.org/searchApi/v2/domain/report/?domain={domain}')
        if tc_data and tc_data.get('response_code') == '1':
            results['threatcrowd'] = {
                'resolutions': tc_data.get('resolutions', [])[:10],
                'emails': tc_data.get('emails', []),
                'subdomains': tc_data.get('subdomains', [])[:20],
                'references': tc_data.get('references', []),
            }
        return results if results else None

    # =========================================================================
    # 8. GOOGLE DORKING (Enhanced - 40+ categories)
    # =========================================================================

    def google_dorks(self, target: str) -> OSINTResult:
        """Generate 40+ Google dork queries for comprehensive target reconnaissance"""
        result = OSINTResult(category="Google Dorks", query=target)

        dorks = {
            # --- File & Document Discovery ---
            "Sensitive files": f'site:{target} ext:pdf OR ext:doc OR ext:xls OR ext:csv OR ext:sql OR ext:log',
            "Config files": f'site:{target} ext:xml OR ext:conf OR ext:cnf OR ext:env OR ext:ini OR ext:yml',
            "Backup files": f'site:{target} ext:bak OR ext:old OR ext:backup OR ext:tmp OR ext:swp',
            "Database files": f'site:{target} ext:sql OR ext:db OR ext:sqlite OR ext:mdb OR ext:dump',
            "Source code": f'site:{target} ext:php OR ext:asp OR ext:jsp OR ext:py OR ext:rb OR ext:js',
            "Exposed documents": f'site:{target} ext:docx OR ext:pptx OR ext:xlsx OR ext:odt',
            "Log files": f'site:{target} ext:log OR filetype:log',
            "Key/cert files": f'site:{target} ext:pem OR ext:key OR ext:crt OR ext:p12 OR ext:pfx',

            # --- Server & Infrastructure ---
            "Login pages": f'site:{target} inurl:login OR inurl:admin OR inurl:signin OR inurl:auth',
            "Admin panels": f'site:{target} inurl:admin OR inurl:cpanel OR inurl:dashboard OR inurl:manage',
            "Directory listing": f'site:{target} intitle:"index of" OR intitle:"directory listing"',
            "Error messages": f'site:{target} "error" OR "warning" OR "fatal" OR "exception" OR "stack trace"',
            "PHP errors": f'site:{target} "Fatal error" OR "Parse error" OR "Warning:" filetype:php',
            "WordPress": f'site:{target} inurl:wp-content OR inurl:wp-admin OR inurl:wp-includes',
            "API endpoints": f'site:{target} inurl:api OR inurl:v1 OR inurl:v2 OR inurl:graphql OR inurl:rest',
            "Open redirects": f'site:{target} inurl:redirect OR inurl:return OR inurl:next OR inurl:url=',
            "Debug/test pages": f'site:{target} inurl:test OR inurl:debug OR inurl:phpinfo OR inurl:staging',
            "Git exposure": f'site:{target} inurl:.git OR intitle:"index of" ".git"',
            "ENV files": f'site:{target} inurl:.env OR filetype:env "DB_PASSWORD" OR "API_KEY"',
            "Swagger/API docs": f'site:{target} inurl:swagger OR inurl:api-docs OR intitle:"Swagger UI"',
            "Server status": f'site:{target} intitle:"Apache Status" OR intitle:"server-status"',

            # --- Credentials & Secrets ---
            "Juicy info": f'site:{target} "password" OR "secret" OR "token" OR "api_key" OR "apikey"',
            "Config passwords": f'site:{target} "DB_PASSWORD" OR "MYSQL_ROOT_PASSWORD" OR "mail_password"',
            "AWS keys": f'site:{target} "AKIA" OR "aws_secret_access_key" OR "AWS_ACCESS_KEY"',
            "Private keys": f'site:{target} "BEGIN RSA PRIVATE KEY" OR "BEGIN PRIVATE KEY"',
            "Connection strings": f'site:{target} "jdbc:" OR "mongodb://" OR "postgres://" OR "mysql://"',

            # --- External Leak Sources ---
            "Pastebin leaks": f'site:pastebin.com "{target}"',
            "GitHub leaks": f'site:github.com "{target}" password OR secret OR token OR api_key',
            "GitLab leaks": f'site:gitlab.com "{target}" password OR secret OR token',
            "Trello boards": f'site:trello.com "{target}"',
            "Jira exposure": f'site:*.atlassian.net "{target}"',
            "StackOverflow leaks": f'site:stackoverflow.com "{target}" password OR config',

            # --- Subdomains & Related ---
            "Subdomains": f'site:*.{target} -www',
            "Related domains": f'"{target}" -site:{target}',
            "Email addresses": f'site:{target} "@{target}"',
            "Phone numbers": f'site:{target} "phone" OR "tel:" OR "mobile" OR "contact"',

            # --- Social Media Dorking ---
            "LinkedIn employees": f'site:linkedin.com/in "{target}"',
            "Facebook mentions": f'site:facebook.com "{target}"',
            "Twitter mentions": f'site:twitter.com OR site:x.com "{target}"',
            "Instagram mentions": f'site:instagram.com "{target}"',
            "YouTube mentions": f'site:youtube.com "{target}"',

            # --- Cached & Archived ---
            "Cached pages": f'cache:{target}',
            "Wayback links": f'site:web.archive.org "{target}"',
        }

        result.data['dorks'] = dorks
        result.data['search_urls'] = {
            name: f'https://www.google.com/search?q={quote(dork)}'
            for name, dork in dorks.items()
        }
        result.data['total_dorks'] = len(dorks)

        self.results.append(result)
        return result

    def google_dorks_person(self, name: str, email: str = "", phone: str = "") -> OSINTResult:
        """Generate Google dorks for person/identity OSINT"""
        result = OSINTResult(category="Person Google Dorks", query=name)

        dorks = {
            "Person search": f'"{name}" -site:facebook.com',
            "Social profiles": f'"{name}" site:linkedin.com OR site:facebook.com OR site:instagram.com OR site:twitter.com',
            "LinkedIn profile": f'site:linkedin.com/in "{name}"',
            "Facebook profile": f'site:facebook.com "{name}"',
            "Resume/CV": f'"{name}" filetype:pdf "resume" OR "curriculum vitae" OR "CV"',
            "Public documents": f'"{name}" filetype:pdf OR filetype:doc OR filetype:docx',
            "News mentions": f'"{name}" site:news.google.com OR inurl:news',
            "Court records": f'"{name}" site:courtlistener.com OR "court" OR "case"',
            "Academic papers": f'"{name}" site:scholar.google.com OR site:researchgate.net OR site:academia.edu',
            "GitHub profile": f'"{name}" site:github.com',
            "Forum posts": f'"{name}" site:reddit.com OR site:quora.com OR inurl:forum',
            "Data breaches": f'"{name}" site:haveibeenpwned.com OR "data breach" OR "leaked"',
            "Cached info": f'"{name}" site:web.archive.org',
        }

        if email:
            dorks["Email search"] = f'"{email}"'
            dorks["Email in documents"] = f'"{email}" filetype:pdf OR filetype:doc OR filetype:xls'
            dorks["Email on Pastebin"] = f'site:pastebin.com "{email}"'
            dorks["Email on GitHub"] = f'site:github.com "{email}"'
            local = email.split('@')[0] if '@' in email else email
            dorks["Email local part"] = f'"{local}" site:linkedin.com OR site:github.com OR site:twitter.com'

        if phone:
            dorks["Phone search"] = f'"{phone}"'
            dorks["Phone in docs"] = f'"{phone}" filetype:pdf OR filetype:doc OR filetype:xls'
            dorks["Phone lookup"] = f'"{phone}" site:truecaller.com OR site:whitepages.com'

        result.data['dorks'] = dorks
        result.data['search_urls'] = {
            name_: f'https://www.google.com/search?q={quote(dork)}'
            for name_, dork in dorks.items()
        }
        result.data['total_dorks'] = len(dorks)

        self.results.append(result)
        return result

    # =========================================================================
    # 9. FULL RECON (all-in-one)
    # =========================================================================

    async def full_recon(self, target: str) -> Dict[str, OSINTResult]:
        """Run comprehensive OSINT on a target (auto-detect type)"""
        results = {}

        # Detect target type and run relevant modules
        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', target):
            results['email'] = await self.email_osint(target)
            domain = target.split('@')[1]
            results['domain'] = await self.domain_recon(domain)
            local = target.split('@')[0]
            results['username'] = await self.username_osint(local, check_live=False)

        elif re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', target):
            results['ip'] = await self.ip_osint(target)

        elif re.match(r'^[\+]?[\d\s\-\(\)]{10,}$', target.strip()):
            results['phone'] = await self.phone_osint(target)

        elif '.' in target and not ' ' in target:
            # Likely a domain
            domain = target.replace('https://', '').replace('http://', '').split('/')[0]
            results['domain'] = await self.domain_recon(domain)
            results['dorks'] = self.google_dorks(domain)
            results['page'] = await self.page_osint(f'https://{domain}')

        else:
            # Assume username
            results['username'] = await self.username_osint(target)

        return results

    # =========================================================================
    # 10. SPIDERFOOT-STYLE SCANNER
    # =========================================================================

    async def spiderfoot_scan(self, target: str, target_type: str = 'auto') -> OSINTResult:
        """
        SpiderFoot-style comprehensive scanner.
        Supports: IP, domain, hostname, CIDR, ASN, email, phone, username,
                  person name, Bitcoin address.
        Auto-detects target type if not specified.
        """
        result = OSINTResult(category="SpiderFoot Scan", query=target)

        # Auto-detect target type
        if target_type == 'auto':
            target_type = self._detect_target_type(target)
        result.data['target_type'] = target_type
        result.data['scan_start'] = datetime.now().isoformat()

        scan_results = {}

        if target_type == 'ip':
            # IP Address scan
            scan_results['ip_info'] = (await self.ip_osint(target)).data
            shodan = await self._api_shodan_internetdb(target)
            if shodan:
                scan_results['shodan_internetdb'] = shodan
            ht_reverse = await self._api_hackertarget(target, 'reversedns')
            if ht_reverse:
                scan_results['reverse_dns_hosts'] = ht_reverse
            try:
                hostname = socket.gethostbyaddr(target)
                if hostname and hostname[0]:
                    dns_result = await self.domain_recon(hostname[0])
                    scan_results['hostname_recon'] = dns_result.data
            except Exception:
                pass

        elif target_type == 'domain':
            domain = target.replace('https://', '').replace('http://', '').strip('/')
            scan_results['domain_recon'] = (await self.domain_recon(domain)).data
            scan_results['google_dorks'] = self.google_dorks(domain).data
            page_result = await self.page_osint(f'https://{domain}')
            scan_results['page_osint'] = page_result.data
            ht_hosts = await self._api_hackertarget(domain, 'hostsearch')
            if ht_hosts:
                scan_results['hackertarget_hosts'] = ht_hosts
            ht_dns = await self._api_hackertarget(domain, 'dnslookup')
            if ht_dns:
                scan_results['hackertarget_dns'] = ht_dns
            urlscan = await self._api_urlscan(domain)
            if urlscan:
                scan_results['urlscan'] = urlscan
            vt_data = await self._api_virustotal_domain(domain)
            if vt_data:
                scan_results['threat_intel'] = vt_data
            # Try to resolve and scan the IP
            ips = self._dns_lookup(domain, 'A')
            for ip in ips[:1]:
                shodan = await self._api_shodan_internetdb(ip)
                if shodan:
                    scan_results['shodan_internetdb'] = shodan

        elif target_type == 'email':
            email_result = await self.email_osint(target)
            scan_results['email_osint'] = email_result.data
            domain = target.split('@')[1]
            scan_results['domain_recon'] = (await self.domain_recon(domain)).data
            local = target.split('@')[0]
            scan_results['username_search'] = (await self.username_osint(local, check_live=True)).data
            scan_results['person_dorks'] = self.google_dorks_person(local, email=target).data

        elif target_type == 'phone':
            phone_result = await self.phone_osint(target)
            scan_results['phone_osint'] = phone_result.data
            # NumVerify data is already embedded in phone_osint result
            if phone_result.data.get('numverify') and isinstance(phone_result.data['numverify'], dict):
                scan_results['numverify_intel'] = phone_result.data['numverify']
            scan_results['phone_dorks'] = {
                'search_urls': {
                    'Google': f'https://www.google.com/search?q="{quote(target)}"',
                    'TrueCaller': f'https://www.truecaller.com/search/{"".join(filter(str.isdigit, target))}',
                    'NumLookup': f'https://www.numlookup.com/lookup/{"".join(filter(str.isdigit, target))}',
                    'Sync.me': f'https://sync.me/search/?number={target}',
                    'WhatsApp': f'https://wa.me/{"".join(filter(str.isdigit, target))}',
                }
            }

        elif target_type == 'username':
            scan_results['username_search'] = (await self.username_osint(target, check_live=True)).data
            gh_data = await self._api_github_user(target)
            if gh_data:
                scan_results['github_profile'] = gh_data
            reddit_data = await self._api_reddit_user(target)
            if reddit_data:
                scan_results['reddit_profile'] = reddit_data
            scan_results['person_dorks'] = self.google_dorks_person(target).data

        elif target_type == 'person_name':
            scan_results['person_dorks'] = self.google_dorks_person(target).data
            # Try username variations
            variations = [
                target.lower().replace(' ', ''),
                target.lower().replace(' ', '.'),
                target.lower().replace(' ', '_'),
            ]
            for v in variations[:2]:
                v_result = await self.username_osint(v, check_live=True)
                if v_result.data.get('found_count', 0) > 0:
                    scan_results[f'username_{v}'] = v_result.data

        elif target_type == 'bitcoin':
            scan_results['bitcoin_info'] = {
                'address': target,
                'explorers': {
                    'Blockchain.com': f'https://www.blockchain.com/explorer/addresses/btc/{target}',
                    'Blockchair': f'https://blockchair.com/bitcoin/address/{target}',
                    'BitRef': f'https://bitref.com/{target}',
                    'WalletExplorer': f'https://www.walletexplorer.com/address/{target}',
                    'OXT': f'https://oxt.me/address/{target}',
                }
            }
            # Try Blockchain.info free API
            bc_data = await self._fetch_json(f'https://blockchain.info/rawaddr/{target}?limit=5')
            if bc_data:
                scan_results['blockchain_data'] = {
                    'total_received': bc_data.get('total_received', 0) / 1e8,
                    'total_sent': bc_data.get('total_sent', 0) / 1e8,
                    'final_balance': bc_data.get('final_balance', 0) / 1e8,
                    'n_tx': bc_data.get('n_tx', 0),
                }

        elif target_type == 'asn':
            asn_num = target.upper().replace('AS', '').replace('ASN', '').strip()
            scan_results['asn_info'] = {
                'asn': f'AS{asn_num}',
                'lookups': {
                    'BGPView': f'https://bgpview.io/asn/{asn_num}',
                    'Hurricane Electric': f'https://bgp.he.net/AS{asn_num}',
                    'RIPE': f'https://stat.ripe.net/AS{asn_num}',
                }
            }
            bgp = await self._fetch_json(f'https://api.bgpview.io/asn/{asn_num}')
            if bgp and bgp.get('status') == 'ok':
                d = bgp.get('data', {})
                scan_results['bgp_data'] = {
                    'name': d.get('name'),
                    'description': d.get('description_full'),
                    'country': d.get('rir_allocation', {}).get('country_code'),
                    'allocated': d.get('rir_allocation', {}).get('date_allocated'),
                    'email_contacts': d.get('email_contacts', []),
                    'abuse_contacts': d.get('abuse_contacts', []),
                }
            # Get prefixes
            prefixes = await self._fetch_json(f'https://api.bgpview.io/asn/{asn_num}/prefixes')
            if prefixes and prefixes.get('status') == 'ok':
                v4_prefixes = prefixes.get('data', {}).get('ipv4_prefixes', [])
                scan_results['ipv4_prefixes'] = [
                    {'prefix': p.get('prefix'), 'name': p.get('name'), 'description': p.get('description')}
                    for p in v4_prefixes[:20]
                ]

        elif target_type == 'cidr':
            scan_results['cidr_info'] = {'subnet': target}
            try:
                network = ipaddress.ip_network(target, strict=False)
                scan_results['cidr_info']['network_address'] = str(network.network_address)
                scan_results['cidr_info']['broadcast_address'] = str(network.broadcast_address)
                scan_results['cidr_info']['num_addresses'] = network.num_addresses
                scan_results['cidr_info']['netmask'] = str(network.netmask)
                # Scan first few hosts
                hosts = list(network.hosts())[:3]
                for host in hosts:
                    ip_str = str(host)
                    shodan = await self._api_shodan_internetdb(ip_str)
                    if shodan and shodan.get('ports'):
                        scan_results[f'host_{ip_str}'] = shodan
            except ValueError as e:
                scan_results['cidr_info']['error'] = str(e)

        result.data = scan_results
        result.data['scan_end'] = datetime.now().isoformat()
        result.data['target_type'] = target_type
        self.results.append(result)
        return result

    @staticmethod
    def _detect_target_type(target: str) -> str:
        """Auto-detect the type of OSINT target"""
        target = target.strip()
        if re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', target):
            return 'email'
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', target):
            return 'ip'
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2}$', target):
            return 'cidr'
        if re.match(r'^(AS|ASN)\s?\d+$', target, re.I):
            return 'asn'
        if re.match(r'^[\+]?[\d\s\-\(\)]{10,}$', target):
            return 'phone'
        if re.match(r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', target):
            return 'bitcoin'
        if re.match(r'^bc1[a-zA-HJ-NP-Z0-9]{39,59}$', target):
            return 'bitcoin'
        if '.' in target and not ' ' in target and len(target) > 3:
            return 'domain'
        if ' ' in target and len(target.split()) >= 2:
            return 'person_name'
        return 'username'

    # =========================================================================
    # 11. POWERFUL SCANNER (Comprehensive Multi-Module Scan)
    # =========================================================================

    async def powerful_scanner(self, email: str, username: str = '',
                                phone: str = '', full_name: str = '',
                                progress_callback=None) -> Dict[str, OSINTResult]:
        """
        Powerful Scanner - comprehensive OSINT combining all modules.
        Takes email (required), username (optional), phone (optional), name (optional).
        Runtime: 1-10 minutes depending on inputs.
        """
        results = {}
        steps_completed = 0

        local_part = email.split('@')[0] if '@' in email else email
        usernames_to_check = {local_part}
        if username:
            usernames_to_check.add(username)

        total_steps = 4
        total_steps += len(usernames_to_check) * 3
        if phone:
            total_steps += 1
        total_steps += 1
        if full_name:
            total_steps += 1

        def _progress(msg: str):
            nonlocal steps_completed
            steps_completed += 1
            if progress_callback:
                progress_callback(min(steps_completed, total_steps), total_steps, msg)

        # === Phase 1: Email Intelligence ===
        _progress("Analyzing email intelligence...")
        email_result = await self.email_osint(email)
        results['email_intelligence'] = email_result

        # === Phase 2: Domain Reconnaissance ===
        domain = email.split('@')[1] if '@' in email else ''
        if domain:
            _progress(f"Scanning domain: {domain}")
            domain_result = await self.domain_recon(domain)
            results['domain_recon'] = domain_result

            # HackerTarget DNS enrichment
            _progress(f"Running DNS enrichment on {domain}...")
            ht = await self._api_hackertarget(domain, 'hostsearch')
            if ht:
                extra = OSINTResult(category="HackerTarget DNS", query=domain)
                extra.data['hosts'] = ht
                results['hackertarget_dns'] = extra

            # URLScan enrichment
            _progress(f"Checking URLScan.io for {domain}...")
            urlscan = await self._api_urlscan(domain)
            if urlscan:
                extra = OSINTResult(category="URLScan Intel", query=domain)
                extra.data = urlscan
                results['urlscan_intel'] = extra

            # Shodan InternetDB for primary IP
            ips = self._dns_lookup(domain, 'A')
            for ip in ips[:1]:
                shodan = await self._api_shodan_internetdb(ip)
                if shodan:
                    extra = OSINTResult(category="Shodan InternetDB", query=ip)
                    extra.data = shodan
                    results['shodan_internetdb'] = extra

        # === Phase 3: Username OSINT ===
        local_part = email.split('@')[0] if '@' in email else email
        usernames_to_check = set()
        usernames_to_check.add(local_part)
        if username:
            usernames_to_check.add(username)

        for uname in usernames_to_check:
            _progress(f"Searching username '{uname}' across 35+ platforms...")
            u_result = await self.username_osint(uname, check_live=True)
            results[f'username_{uname}'] = u_result

            # GitHub enrichment
            _progress(f"Fetching GitHub profile for '{uname}'...")
            gh = await self._api_github_user(uname)
            if gh:
                extra = OSINTResult(category="GitHub Profile", query=uname)
                extra.data = gh
                results[f'github_{uname}'] = extra

            # Reddit enrichment
            _progress(f"Fetching Reddit profile for '{uname}'...")
            reddit = await self._api_reddit_user(uname)
            if reddit:
                extra = OSINTResult(category="Reddit Profile", query=uname)
                extra.data = reddit
                results[f'reddit_{uname}'] = extra

        # === Phase 4: Phone OSINT ===
        if phone:
            _progress(f"Analyzing phone number: {phone}")
            phone_result = await self.phone_osint(phone)
            results['phone_osint'] = phone_result

        # === Phase 5: Person Dorks ===
        search_name = full_name or local_part
        _progress(f"Generating Google dorks for '{search_name}'...")
        person_dorks = self.google_dorks_person(
            search_name, email=email, phone=phone
        )
        results['google_dorks_person'] = person_dorks

        # Domain-specific dorks
        if domain:
            domain_dorks = self.google_dorks(domain)
            results['google_dorks_domain'] = domain_dorks

        # === Phase 6: Name-based search ===
        if full_name:
            _progress(f"Searching for person: {full_name}")
            # Try name as username variations
            variations = [
                full_name.lower().replace(' ', ''),
                full_name.lower().replace(' ', '.'),
                full_name.lower().replace(' ', '_'),
            ]
            for v in variations:
                if v not in usernames_to_check:
                    v_result = await self.username_osint(v, check_live=True)
                    if v_result.data.get('found_count', 0) > 0:
                        results[f'name_variation_{v}'] = v_result
                    break  # Only try the most likely one

        # === Build Summary ===
        summary = OSINTResult(category="Powerful Scanner Summary", query=email)
        summary.data['scan_inputs'] = {
            'email': email,
            'username': username or '(not provided)',
            'phone': phone or '(not provided)',
            'full_name': full_name or '(not provided)',
        }

        # Aggregate key findings
        total_profiles_found = 0
        all_verified_profiles = {}
        for key, res in results.items():
            if hasattr(res, 'data'):
                vp = res.data.get('verified_profiles', {})
                if vp:
                    all_verified_profiles.update(vp)
                    total_profiles_found += len(vp)
                fp = res.data.get('found_profiles', {})
                if fp:
                    all_verified_profiles.update(fp)
                    total_profiles_found += len(fp)

        summary.data['total_profiles_found'] = total_profiles_found
        summary.data['all_profiles'] = all_verified_profiles
        summary.data['modules_run'] = len(results)
        summary.data['scan_complete'] = datetime.now().isoformat()
        results['_summary'] = summary

        return results

    # =========================================================================
    # 12. AI-POWERED OSINT ANALYSIS (OpenRouter + Serper + SearXNG)
    # =========================================================================

    async def _api_serper_search(self, query: str, num_results: int = 3) -> Optional[Dict]:
        """
        Serper.dev — real-time Google Search API.
        Default 3 results to conserve credits (each call = 1 credit).
        """
        api_key = os.environ.get('SERPER_API_KEY', '')
        if not api_key or api_key == 'your-serper-key-here':
            logger.debug("Serper API key not configured")
            return None

        await self._ensure_session()
        try:
            payload = json.dumps({"q": query, "num": min(num_results, 5)})
            headers = {
                'X-API-KEY': api_key,
                'Content-Type': 'application/json',
            }
            async with self.session.post(
                'https://google.serper.dev/search',
                data=payload, headers=headers, ssl=False
            ) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    results = {
                        'query': query,
                        'search_engine': 'Google (via Serper)',
                        'organic_results': [],
                    }
                    # Only keep title + snippet (skip full URL to save AI tokens)
                    for item in data.get('organic', [])[:num_results]:
                        results['organic_results'].append({
                            'title': item.get('title', ''),
                            'link': item.get('link', ''),
                            'snippet': item.get('snippet', '')[:150],
                        })
                    return results
                else:
                    logger.debug(f"Serper API error: HTTP {r.status}")
        except Exception as e:
            logger.debug(f"Serper API error: {e}")
        return None

    async def _api_searxng_search(self, query: str, num_results: int = 3) -> Optional[Dict]:
        """
        SearXNG — free self-hosted metasearch engine (fallback for Serper).
        Default 3 results to keep AI context small.
        """
        base_url = os.environ.get('SEARXNG_URL', 'http://localhost:8888')
        await self._ensure_session()
        try:
            params = {
                'q': query,
                'format': 'json',
                'categories': 'general',
                'language': 'en',
                'pageno': 1,
            }
            async with self.session.get(
                f'{base_url}/search',
                params=params, ssl=False,
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    results = {
                        'query': query,
                        'search_engine': 'SearXNG (self-hosted)',
                        'organic_results': [],
                    }
                    for item in data.get('results', [])[:num_results]:
                        results['organic_results'].append({
                            'title': item.get('title', ''),
                            'link': item.get('url', ''),
                            'snippet': item.get('content', '')[:150],
                        })
                    return results
        except Exception as e:
            logger.debug(f"SearXNG search error: {e}")
        return None

    async def web_search(self, query: str, num_results: int = 3) -> Optional[Dict]:
        """
        Web search with fallback: Serper → SearXNG.
        Default 3 results to save credits and AI tokens.
        """
        # Try Serper first (1 credit per call regardless of num_results)
        result = await self._api_serper_search(query, num_results)
        if result and result.get('organic_results'):
            return result

        # Fallback to SearXNG (free, self-hosted)
        result = await self._api_searxng_search(query, num_results)
        if result and result.get('organic_results'):
            return result

        return None

    async def ai_analyze(self, prompt: str, context: str = '',
                         search_queries: List[str] = None,
                         system_prompt: str = None) -> OSINTResult:
        """
        AI-powered OSINT analysis using OpenRouter API.
        Primary:  cognitivecomputations/dolphin-mistral-24b-venice-edition:free
        Fallback: arcee-ai/trinity-large-preview:free

        If search_queries are provided, performs live web searches first
        (via Serper/SearXNG) and includes results in the AI context.

        Args:
            prompt: The analysis question/task for the AI
            context: Optional OSINT data to analyze
            search_queries: Optional Google dork queries to search live
            system_prompt: Optional custom system prompt
        """
        result = OSINTResult(category="AI Analysis", query=prompt[:100])

        api_key = os.environ.get('OPENROUTER_API_KEY', '')
        if not api_key or api_key == 'sk-or-v1-your-key-here':
            result.success = False
            result.error = "OpenRouter API key not configured"
            result.data['setup_instructions'] = {
                'step_1': 'Go to https://openrouter.ai/keys and create a free API key',
                'step_2': f'Edit {os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")}',
                'step_3': 'Set OPENROUTER_API_KEY=sk-or-v1-your-actual-key',
                'step_4': 'Restart the tool',
            }
            self.results.append(result)
            return result

        # --- Phase 1: Live web search if queries provided ---
        search_context = ""
        if search_queries:
            result.data['search_queries'] = search_queries
            search_results_all = []
            for sq in search_queries[:3]:  # Max 3 queries (saves Serper credits)
                sr = await self.web_search(sq, num_results=3)
                if sr:
                    search_results_all.append(sr)
                    # Compact format: title + snippet only (saves AI tokens)
                    for item in sr.get('organic_results', []):
                        search_context += f"\n- {item.get('title', '')}: {item.get('snippet', '')[:100]}"

            result.data['search_results'] = search_results_all
            if search_context:
                search_context = f"\n\nSearch results:{search_context}\n"

        # --- Phase 2: Build AI prompt (compact to save tokens) ---
        if not system_prompt:
            system_prompt = (
                "You are an OSINT analyst. Be concise. Use bullet points. "
                "Identify patterns, risks, and actionable intelligence."
            )

        # Truncate context to save tokens (max ~4000 chars ≈ 1000 tokens)
        if context and len(context) > 4000:
            context = context[:3900] + '\n... [truncated to save tokens]'

        full_prompt = prompt
        if context:
            full_prompt += f"\n\nData:\n{context}"
        if search_context:
            full_prompt += search_context

        # --- Phase 3: Call OpenRouter API ---
        models = [
            "cognitivecomputations/dolphin-mistral-24b-venice-edition:free",
            "arcee-ai/trinity-large-preview:free",
        ]

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://github.com/osint-tool',
            'X-Title': 'OSINT Intelligence Tool',
        }

        ai_response = None
        model_used = None
        model_errors = []

        await self._ensure_session()
        for i, model in enumerate(models):
            try:
                payload = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": full_prompt},
                    ],
                    "max_tokens": 2048,
                    "temperature": 0.3,
                })

                async with self.session.post(
                    'https://openrouter.ai/api/v1/chat/completions',
                    data=payload, headers=headers, ssl=False,
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        # Check for OpenRouter error in response body
                        if 'error' in data:
                            err_msg = data['error'].get('message', str(data['error'])) if isinstance(data['error'], dict) else str(data['error'])
                            model_errors.append(f"{model}: {err_msg}")
                            logger.warning(f"OpenRouter {model} returned error: {err_msg}")
                            continue
                        choices = data.get('choices', [])
                        if choices:
                            ai_response = choices[0].get('message', {}).get('content', '')
                            if ai_response:  # Only accept non-empty responses
                                model_used = model
                                result.data['usage'] = data.get('usage', {})
                                if i > 0:
                                    result.data['fallback_reason'] = model_errors
                                break
                            else:
                                model_errors.append(f"{model}: Empty response")
                                continue
                        else:
                            model_errors.append(f"{model}: No choices in response")
                            continue
                    else:
                        error_text = await r.text()
                        err_msg = f"HTTP {r.status}"
                        try:
                            err_data = json.loads(error_text)
                            if 'error' in err_data:
                                err_detail = err_data['error']
                                err_msg = err_detail.get('message', error_text[:200]) if isinstance(err_detail, dict) else str(err_detail)[:200]
                        except (json.JSONDecodeError, AttributeError):
                            err_msg = f"HTTP {r.status} — {error_text[:200]}"
                        model_errors.append(f"{model}: {err_msg}")
                        logger.warning(f"OpenRouter {model} failed: {err_msg}")

            except asyncio.TimeoutError:
                model_errors.append(f"{model}: Request timed out (120s)")
                logger.warning(f"OpenRouter {model} timed out")
                continue
            except Exception as e:
                model_errors.append(f"{model}: {str(e)[:100]}")
                logger.warning(f"OpenRouter {model} error: {e}")
                continue

        if ai_response:
            result.data['model_used'] = model_used
            result.data['analysis'] = ai_response
            result.data['prompt'] = prompt[:200]
            result.sources = [f"OpenRouter ({model_used})", "Serper" if search_context else ""]
            result.sources = [s for s in result.sources if s]
        else:
            result.success = False
            result.error = "All AI models failed. Check your API key or try again later."

        self.results.append(result)
        return result

    async def ai_dork_search(self, target: str, dork_type: str = 'all') -> OSINTResult:
        """
        AI-powered Google Dorking: generates dorks for ANY target type
        (domain, person name, email, username, file, keyword, etc.),
        searches live via Serper/SearXNG, then feeds results to AI for analysis.
        """
        result = OSINTResult(category="AI Dork Search", query=target)

        # --- Auto-detect target type and generate appropriate dorks ---
        target_type = self._detect_target_type(target)
        result.data['detected_type'] = target_type

        dorks = {}

        if target_type == 'domain':
            # Domain-specific dorks (existing)
            dork_result = self.google_dorks(target)
            dorks = dork_result.data.get('dorks', {})
        elif target_type == 'email':
            # Email-specific dorks
            local = target.split('@')[0] if '@' in target else target
            domain = target.split('@')[1] if '@' in target else ''
            dork_result = self.google_dorks_person(local, email=target)
            dorks = dork_result.data.get('dorks', {})
            # Add extra email dorks
            dorks['Email everywhere'] = f'"{target}"'
            dorks['Email in pastes'] = f'"{target}" site:pastebin.com OR site:ghostbin.com OR site:paste.ee'
            dorks['Email in breaches'] = f'"{target}" "breach" OR "leak" OR "dump" OR "database"'
            dorks['Email on dark web'] = f'"{target}" site:reddit.com/r/netsec OR site:reddit.com/r/privacy'
            if domain:
                dorks['Email domain files'] = f'site:{domain} filetype:pdf OR filetype:doc OR filetype:xls'
        elif target_type in ('person_name', 'username'):
            # Person/username dorks
            dork_result = self.google_dorks_person(target)
            dorks = dork_result.data.get('dorks', {})
            # Add extra people dorks
            dorks['Name everywhere'] = f'"{target}"'
            dorks['Name + password'] = f'"{target}" password OR credentials OR login'
            dorks['Name + phone'] = f'"{target}" phone OR mobile OR "contact"'
            dorks['Name + address'] = f'"{target}" address OR location OR city OR "lives in"'
            dorks['Name + employer'] = f'"{target}" employer OR company OR "works at" OR "worked at"'
            dorks['Name + education'] = f'"{target}" university OR school OR degree OR "studied at"'
            dorks['Name in documents'] = f'"{target}" filetype:pdf OR filetype:doc OR filetype:pptx'
            dorks['Name in code'] = f'"{target}" site:github.com OR site:gitlab.com OR site:stackoverflow.com'
            dorks['Name in databases'] = f'"{target}" site:haveibeenpwned.com OR "data breach" OR "leaked"'
        elif target_type == 'phone':
            # Phone number dorks
            clean = re.sub(r'[^\d+]', '', target)
            dorks['Phone everywhere'] = f'"{target}" OR "{clean}"'
            dorks['Phone in docs'] = f'"{target}" filetype:pdf OR filetype:doc OR filetype:xls'
            dorks['Phone lookup'] = f'"{target}" site:truecaller.com OR site:whitepages.com OR site:sync.me'
            dorks['Phone on social'] = f'"{target}" site:facebook.com OR site:linkedin.com OR site:instagram.com'
            dorks['Phone in pastes'] = f'"{target}" site:pastebin.com OR site:ghostbin.com'
            dorks['Phone + name'] = f'"{target}" name OR person OR contact OR owner'
            dorks['Phone + address'] = f'"{target}" address OR location OR city'
        elif target_type == 'ip':
            dorks['IP everywhere'] = f'"{target}"'
            dorks['IP in logs'] = f'"{target}" filetype:log OR filetype:txt "access" OR "error"'
            dorks['IP in configs'] = f'"{target}" filetype:conf OR filetype:cfg OR filetype:xml'
            dorks['IP on Shodan'] = f'site:shodan.io "{target}"'
            dorks['IP abuse'] = f'"{target}" "abuse" OR "malicious" OR "blacklist" OR "spam"'
            dorks['IP in pastes'] = f'"{target}" site:pastebin.com OR site:github.com'
        else:
            # Generic keyword/file dorks — works for anything
            dorks['Keyword everywhere'] = f'"{target}"'
            dorks['Keyword in files'] = f'"{target}" filetype:pdf OR filetype:doc OR filetype:xls OR filetype:csv'
            dorks['Keyword in configs'] = f'"{target}" filetype:conf OR filetype:env OR filetype:yml OR filetype:xml'
            dorks['Keyword in code'] = f'"{target}" filetype:py OR filetype:js OR filetype:php OR filetype:java'
            dorks['Keyword in pastes'] = f'"{target}" site:pastebin.com OR site:ghostbin.com OR site:hastebin.com'
            dorks['Keyword on GitHub'] = f'"{target}" site:github.com'
            dorks['Keyword in databases'] = f'"{target}" filetype:sql OR filetype:db OR filetype:csv "password" OR "user"'
            dorks['Keyword + leaked'] = f'"{target}" "leak" OR "breach" OR "dump" OR "exposed"'
            dorks['Keyword + social'] = f'"{target}" site:linkedin.com OR site:facebook.com OR site:twitter.com'
            dorks['Keyword + news'] = f'"{target}" site:news.google.com OR inurl:news OR inurl:article'

        # Select dork subset based on dork_type filter
        if dork_type == 'security':
            keys = [k for k in dorks if any(w in k.lower() for w in
                    ['sensitive', 'config', 'login', 'juicy', 'aws', 'private', 'env', 'git',
                     'password', 'credential', 'leak', 'breach', 'database', 'abuse'])]
        elif dork_type == 'social':
            keys = [k for k in dorks if any(w in k.lower() for w in
                    ['linkedin', 'facebook', 'twitter', 'instagram', 'social', 'profile',
                     'employer', 'education', 'name', 'phone', 'address'])]
        elif dork_type == 'leaks':
            keys = [k for k in dorks if any(w in k.lower() for w in
                    ['paste', 'github', 'gitlab', 'trello', 'stackoverflow', 'leak',
                     'breach', 'dump', 'database', 'password'])]
        else:
            keys = list(dorks.keys())

        if not keys:
            keys = list(dorks.keys())

        selected_dorks = [dorks[k] for k in keys[:10]]

        if not selected_dorks:
            result.error = "No dorks generated"
            result.success = False
            return result

        result.data['target_type'] = target_type
        result.data['dork_categories'] = keys[:10]

        # Search live for each dork
        all_search_results = {}
        for dork in selected_dorks[:6]:  # Max 6 to avoid rate limits
            sr = await self.web_search(dork, num_results=5)
            if sr and sr.get('organic_results'):
                all_search_results[dork] = sr['organic_results']

        result.data['dorks_searched'] = len(selected_dorks)
        result.data['dorks_with_results'] = len(all_search_results)
        result.data['raw_results'] = all_search_results

        # Feed to AI for analysis
        if all_search_results:
            context = json.dumps(all_search_results, indent=2, default=str)
            ai_prompt = (
                f"Analyze these Google Dork search results for target '{target}' "
                f"(detected type: {target_type}). "
                f"Identify: exposed information, leaked data, digital footprint, "
                f"security risks, personal information exposure, connected accounts, "
                f"and any actionable intelligence. "
                f"Rate the overall exposure level (Low/Medium/High/Critical)."
            )
            ai_result = await self.ai_analyze(ai_prompt, context=context)
            if ai_result.success:
                result.data['ai_analysis'] = ai_result.data.get('analysis', '')
                result.data['model_used'] = ai_result.data.get('model_used', '')
                if ai_result.data.get('fallback_reason'):
                    result.data['model_fallback'] = ai_result.data['fallback_reason']

        result.sources = list(set(["Google Dorks", "Serper/SearXNG", "OpenRouter AI"]))
        self.results.append(result)
        return result

    # =========================================================================
    # 13. RESOURCE LOOKUP
    # =========================================================================

    @staticmethod
    def get_tools(category: str) -> List[Dict]:
        """Get OSINT tools for a category"""
        cat = category.lower().replace(' ', '_').replace('-', '_')
        res = OSINT_RESOURCES.get(cat, {})
        return res.get('tools', [])

    @staticmethod
    def list_categories() -> List[str]:
        """List all OSINT categories"""
        return sorted(OSINT_RESOURCES.keys())

    @staticmethod
    def search_tools(keyword: str) -> List[Dict]:
        """Search across all OSINT tools"""
        keyword = keyword.lower()
        found = []
        for cat, data in OSINT_RESOURCES.items():
            for tool in data.get('tools', []):
                if keyword in tool['name'].lower() or keyword in tool['desc'].lower():
                    found.append({**tool, 'category': cat})
        return found

    # =========================================================================
    # 13. ENCODING / DECODING
    # =========================================================================

    @staticmethod
    def encode_decode(text: str) -> Dict[str, str]:
        """Encode/decode text in multiple formats"""
        results = {}
        b = text.encode('utf-8')
        results['base64'] = base64.b64encode(b).decode()
        results['hex'] = b.hex()
        results['url_encoded'] = quote(text)
        results['md5'] = hashlib.md5(b).hexdigest()
        results['sha1'] = hashlib.sha1(b).hexdigest()
        results['sha256'] = hashlib.sha256(b).hexdigest()
        results['rot13'] = text.translate(str.maketrans(
            'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz',
            'NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm'))
        results['binary'] = ' '.join(format(byte, '08b') for byte in b)
        results['decimal'] = ' '.join(str(byte) for byte in b)
        # Try base64 decode
        try:
            results['base64_decoded'] = base64.b64decode(text).decode('utf-8', errors='replace')
        except Exception:
            results['base64_decoded'] = '[not valid base64]'
        return results

    # =========================================================================
    # 14. EXPORT
    # =========================================================================

    def export_results(self, filepath: str = None, format: str = 'json') -> str:
        """Export results to JSON, CSV, or HTML"""
        if not filepath:
            ext = {'json': '.json', 'csv': '.csv', 'html': '.html'}.get(format, '.json')
            filepath = os.path.join(os.path.expanduser('~'), 'scraper', f'osint_results{ext}')
        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        if format == 'json':
            data = {
                'export_time': datetime.now().isoformat(),
                'total_queries': len(self.results),
                'results': [r.to_dict() for r in self.results]
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, default=str)

        elif format == 'csv':
            import csv
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp', 'category', 'query', 'success', 'data_keys', 'error'])
                for r in self.results:
                    writer.writerow([
                        r.timestamp, r.category, r.query, r.success,
                        '|'.join(r.data.keys()), r.error or ''
                    ])

        elif format == 'html':
            html_parts = [
                '<html><head><title>OSINT Report</title>',
                '<style>body{font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:20px}',
                '.result{border:1px solid #333;padding:15px;margin:10px 0;border-radius:8px}',
                '.success{border-left:4px solid #00ff88}.error{border-left:4px solid #ff4444}',
                'h2{color:#00ff88}pre{white-space:pre-wrap;word-wrap:break-word}</style></head><body>',
                f'<h1>OSINT Report — {datetime.now().strftime("%Y-%m-%d %H:%M")}</h1>',
            ]
            for r in self.results:
                cls = 'success' if r.success else 'error'
                html_parts.append(f'<div class="result {cls}"><h2>{r.category}</h2>')
                html_parts.append(f'<p><b>Query:</b> {r.query} | <b>Time:</b> {r.timestamp}</p>')
                if r.error:
                    html_parts.append(f'<p style="color:#ff4444">Error: {r.error}</p>')
                html_parts.append(f'<pre>{json.dumps(r.data, indent=2, default=str)}</pre></div>')
            html_parts.append('</body></html>')
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(html_parts))

        logger.info(f"Results exported to {filepath}")
        return filepath

    def print_all(self):
        """Print all results"""
        for r in self.results:
            print(r.summary())

