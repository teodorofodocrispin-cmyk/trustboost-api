"""
seo_pages_data.py

Contenido de cada página de "búsqueda de miedo" (SEO programático).
Para agregar una plataforma nueva, copia una entrada existente, cambia
el texto, y ya — no hace falta tocar main.py ni crear ningún archivo
nuevo. La ruta /check/{slug} en main.py sirve cualquier entrada de aquí
automáticamente.

Cada entrada necesita:
  - title: para la pestaña del navegador y Google
  - meta_description: lo que Google muestra debajo del título en resultados
  - hero_h1: el titular grande de la página
  - hero_lede: el párrafo debajo del titular
  - faq_heading: título de la sección de preguntas frecuentes
  - faq_items: el HTML de las preguntas y respuestas (ver el formato abajo)
"""

FAQ_ITEM_TEMPLATE = """
        <h3 style="font-size:1.02rem; margin:0 0 6px;">{question}</h3>
        <p style="color:var(--text-dim); font-size:0.92rem; margin:0 0 20px;">{answer}</p>"""


def _build_faq(items: list[tuple[str, str]]) -> str:
    """items es una lista de (pregunta, respuesta). Arma el HTML final."""
    return "".join(FAQ_ITEM_TEMPLATE.format(question=q, answer=a) for q, a in items)


SEO_PAGES = {

    "lovable": {
        "title": "Is Your Lovable App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Lovable app is exposing user data through Supabase. Free, read-only scan — the same class of issue behind CVE-2025-48757, which affected 170+ live Lovable apps.",
        "hero_h1": "Is your Lovable app safe? Find out in under a minute.",
        "hero_lede": "In 2025, a single missing security setting exposed live user data across more than 170 Lovable apps (tracked as CVE-2025-48757). A second incident in April 2026 let any free account browse other users' project source code and database credentials. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Lovable security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Lovable safe to use?",
             "Lovable itself is a legitimate, widely used platform. The risk isn't the platform — it's that apps it generates connect to a Supabase database, and Supabase requires you to turn security rules on explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("What was CVE-2025-48757?",
             "A documented vulnerability where more than 170 live Lovable apps — about one in ten scanned at the time — had inadequate Row Level Security on their Supabase backend, letting unauthenticated visitors read data like names, emails, and in some cases financial details. It was assigned a CVSS score of 9.3, in the critical range."),
            ("What happened in the April 2026 Lovable incident?",
             "A separate issue let any free Lovable account read other users' project source code, database credentials, and chat history for projects created before November 2025. It was patched, but it's a reminder that this class of issue keeps recurring across AI app builders, not just Lovable."),
            ("How do I check if my Lovable app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
        ]),
    },

    "bolt": {
        "title": "Is Your Bolt.new App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Bolt.new app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your Bolt.new app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI tools like Bolt.new found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Bolt.new security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Bolt.new safe to use?",
             "Bolt.new is a legitimate, widely used AI app builder. The risk isn't the platform — it's that apps it generates typically connect to a Supabase database, and Supabase requires you to turn on security rules explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in Bolt.new apps?",
             "Independent research auditing thousands of apps generated by AI coding tools (Bolt.new included) has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my Bolt.new app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
        ]),
    },

    "base44": {
        "title": "Is Your Base44 App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Base44 app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your Base44 app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI tools like Base44 found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Base44 security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Base44 safe to use?",
             "Base44 is a legitimate, widely used AI app builder. The risk isn't the platform — it's that apps it generates typically connect to a Supabase database, and Supabase requires you to turn on security rules explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in Base44 apps?",
             "Independent research auditing thousands of apps generated by AI coding tools has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my Base44 app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
        ]),
    },

    "replit": {
        "title": "Is Your Replit App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Replit app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your Replit app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI coding tools, Replit Agent included, found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Replit app security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Replit Agent safe to use?",
             "Replit is a legitimate, widely used development platform. The risk isn't the platform — it's that apps generated by AI agents typically connect to a Supabase database, and Supabase requires you to turn on security rules explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in Replit apps?",
             "Independent research auditing thousands of apps generated by AI coding tools has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my Replit app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
        ]),
    },

}
