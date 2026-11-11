
 
import os
import sys
import json
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
 
import requests
from bs4 import BeautifulSoup
 
from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.toolkit import Toolkit
from dotenv import load_dotenv

load_dotenv()
 
 
# ─────────────────────────────────────────────
# TOOLKIT: Google Patents scraper
# ─────────────────────────────────────────────
 
class GooglePatentsTool(Toolkit):
    """Toolkit agno per interrogare Google Patents tramite HTTP."""
 
    def __init__(self):
        super().__init__(name="google_patents_tool")
 
    def search_patents(self, keywords: str, max_results: int = 10) -> str:
        """
        Cerca brevetti su Google Patents in base alle keywords fornite.
        Restituisce una lista JSON con i 10 brevetti più rilevanti.
 
        Args:
            keywords: parole chiave di ricerca (es. 'plant sensor IoT AI digital passport')
            max_results: numero massimo di risultati (default 10)
 
        Returns:
            JSON string con lista di brevetti trovati.
        """
        try:
            # Calcola data limite: solo brevetti post-2006 (validi)
            cutoff_year = (datetime.now().year - 20) + 1  # brevetti non ancora scaduti
 
            # Costruisci query Google Patents
            query = urllib.parse.quote(keywords)
            url = (
                f"https://patents.google.com/xhr/query"
                f"?url=q%3D{query}"
                f"%26after%3Dpriority%3A{cutoff_year}0101"
                f"%26num%3D{max_results}"
                f"&exp=&key=AIzaSyCeztp_-zsHHSJCqBMNiCnrFnAt6zyyfME"
            )
 
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": "https://patents.google.com/",
            }
 
            resp = requests.get(url, headers=headers, timeout=15)
 
            if resp.status_code != 200:
                # Fallback: scraping HTML classico
                return self._scrape_html_fallback(keywords, max_results, cutoff_year)
 
            data = resp.json()
            results = self._parse_api_response(data, max_results)
 
            if not results:
                return self._scrape_html_fallback(keywords, max_results, cutoff_year)
 
            return json.dumps(results, ensure_ascii=False, indent=2)
 
        except Exception as e:
            return json.dumps({"error": str(e), "patents": []})
 
    def _parse_api_response(self, data: dict, max_results: int) -> list:
        """Parsa la risposta JSON dell'API di Google Patents."""
        patents = []
        clusters = data.get("results", {}).get("cluster", [])
 
        for cluster in clusters[:max_results]:
            patent = cluster.get("patent", {})
            if not patent:
                continue
 
            filing_date = patent.get("filing_date", "")
            pub_date = patent.get("publication_date", "")
 
            # Determina se scaduto (filing > 20 anni fa)
            is_active = True
            if filing_date:
                try:
                    fd = datetime.strptime(filing_date[:8], "%Y%m%d")
                    is_active = (datetime.now() - fd).days < 365 * 20
                except Exception:
                    pass
 
            patents.append({
                "patent_id": patent.get("publication_number", "N/A"),
                "title": patent.get("title", "No title"),
                "assignee": patent.get("assignee", ["Unknown"]),
                "filing_date": filing_date,
                "publication_date": pub_date,
                "abstract": patent.get("abstract", "")[:500],
                "url": f"https://patents.google.com/patent/{patent.get('publication_number', '')}",
                "is_active": is_active,
                "status": "ATTIVO ⚠️" if is_active else "SCADUTO ✅",
            })
 
        return patents
 
    def _scrape_html_fallback(self, keywords: str, max_results: int, cutoff_year: int) -> str:
        """Fallback: scraping HTML di Google Patents."""
        try:
            query = urllib.parse.quote(keywords)
            url = (
                f"https://patents.google.com/?"
                f"q={query}"
                f"&after=priority:{cutoff_year}0101"
                f"&num={max_results}"
            )
 
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
 
            resp = requests.get(url, headers=headers, timeout=20)
            soup = BeautifulSoup(resp.text, "html.parser")
 
            patents = []
            # Google Patents usa tag search-result-item
            items = soup.find_all("article", class_=re.compile("result"))
 
            if not items:
                # Struttura alternativa
                items = soup.select("search-result-item, .result-item, [data-result]")
 
            for item in items[:max_results]:
                title_el = item.find(["h3", "h4", "span"], class_=re.compile("title|heading"))
                title = title_el.get_text(strip=True) if title_el else "N/A"
 
                pid_el = item.find(class_=re.compile("patent-number|publication"))
                patent_id = pid_el.get_text(strip=True) if pid_el else "N/A"
 
                patents.append({
                    "patent_id": patent_id,
                    "title": title,
                    "assignee": "N/A",
                    "filing_date": "N/A",
                    "abstract": "",
                    "url": f"https://patents.google.com/?q={query}",
                    "is_active": True,
                    "status": "DA VERIFICARE",
                })
 
            if not patents:
                # Se scraping fallisce, restituisce istruzioni
                patents = [{
                    "note": (
                        "Scraping bloccato da Google. "
                        "Usa SerpAPI o Google Patents BigQuery per accesso programmatico. "
                        "URL manuale: " + url
                    ),
                    "manual_url": url
                }]
 
            return json.dumps(patents, ensure_ascii=False, indent=2)
 
        except Exception as e:
            return json.dumps({"error": f"Scraping failed: {e}"})
 
 
# ─────────────────────────────────────────────
# AGENT
# ─────────────────────────────────────────────
 
SYSTEM_PROMPT = """Sei un esperto di proprietà intellettuale e ricerca brevettuale.
Il tuo compito è:
1. Usare lo strumento search_patents con le keywords fornite dall'utente
2. Analizzare i brevetti trovati
3. Produrre un report strutturato con:
   - Lista dei 10 brevetti più simili all'idea (con ID, titolo, assignee, stato attivo/scaduto)
   - Analisi del rischio per ciascun brevetto (alto/medio/basso)
   - VERDETTO FINALE: 🟢 IDEA LIBERA / 🔴 IDEA BLOCCATA / 🟡 AREA GRIGIA
   - Spiegazione del verdetto in 3-4 righe
   - Consigli su differenziazione o strade alternative
 
Ricorda:
- Un brevetto ATTIVO (filing < 20 anni) è una potenziale barriera
- Un brevetto SCADUTO è prior art utile ma non blocca
- Brevetti con claims simili alla combinazione specifica dell'utente sono i più pericolosi
- Sei consulente tecnico, NON avvocato: raccomanda sempre di consultare un IP lawyer per decisioni legali definitive.
 
Rispondi SEMPRE in italiano."""
 
 
def build_agent(api_key: Optional[str] = None) -> Agent:
    """Costruisce e restituisce l'agente agno."""
    key = api_key or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("❌ GOOGLE_API_KEY non trovata. Impostala nel file .env:\n   GOOGLE_API_KEY=...")
        sys.exit(1)
 
    tool = GooglePatentsTool()
 
    agent = Agent(
        model=Gemini(id="gemini-2.5-flash", api_key=key),
        tools=[tool],
        description=[SYSTEM_PROMPT],
        markdown=True,
        instructions=[
            "Chiama sempre search_patents prima di rispondere.",
            "Se i risultati sono pochi o ambigui, dillo esplicitamente.",
            "Il verdetto finale deve essere sempre presente e chiaro.",
        ],
    )
    return agent
 
 
# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
 
def main():
    print("=" * 60)
    print("  🔍 PATENT SEARCH AGENT - powered by agno + Gemini")
    print("=" * 60)
    print()
 
    # Input utente
    print("Descrivi la tua idea brevettuale.")
    print("Inserisci le keywords (es: 'plant sensor IoT AI digital passport indoor'):")
    print()
 
    keywords = input(">>> Keywords: ").strip()
    if not keywords:
        print("❌ Nessuna keyword inserita. Uscita.")
        sys.exit(1)
 
    print()
    print("Vuoi aggiungere dettagli extra sull'idea? (opzionale, premi INVIO per saltare):")
    extra = input(">>> Descrizione: ").strip()
 
    # Costruisci query completa
    if extra:
        user_message = (
            f"Cerca brevetti per questa idea:\n\n"
            f"KEYWORDS: {keywords}\n\n"
            f"DESCRIZIONE IDEA: {extra}\n\n"
            f"Analizza i risultati e dammi il verdetto finale."
        )
    else:
        user_message = (
            f"Cerca brevetti per le seguenti keywords: {keywords}\n\n"
            f"Analizza i risultati e dammi il verdetto finale sulla libertà dell'idea."
        )
 
    print()
    print("=" * 60)
    print("  🤖 Avvio ricerca...")
    print("=" * 60)
    print()
 
    agent = build_agent()
 
    try:
        agent.print_response(user_message, stream=True)

    except KeyboardInterrupt:
        print("\n\n⛔ Ricerca interrotta dall'utente.")
    except Exception as e:
        print(f"\n❌ Errore: {e}")
        raise

# sensor, indoor, plant, ai 

# intelligent sensors that collects indoor plant's datas and by using ai it elaborates them in search 
# of potential illnesses and gives a feedback to a human in order to prevent. 
# so the system is based on hardware(sensors), database and software(web app and ai agents)
 
 
if __name__ == "__main__":
    main()