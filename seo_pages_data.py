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
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
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
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
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
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
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
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
        ]),
    },

    "v0": {
        "title": "Is Your v0 App Safe? Free Supabase Security Check",
        "meta_description": "Check if your v0 (Vercel) app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your v0 app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI tools like v0 found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "v0 app security, answered plainly.",
        "faq_items": _build_faq([
            ("Is v0 safe to use?",
             "v0 is a legitimate, widely used AI app builder from Vercel. The risk isn't the platform — it's that apps built with it often connect to a Supabase database, and Supabase requires you to turn on security rules explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in v0 apps?",
             "Independent research auditing thousands of apps generated by AI coding tools has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my v0 app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
        ]),
    },

    "create": {
        "title": "Is Your Create.xyz App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Create.xyz app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your Create.xyz app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI tools like Create.xyz found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Create.xyz security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Create.xyz safe to use?",
             "Create.xyz is a legitimate, widely used AI app builder. The risk isn't the platform — it's that apps it generates often connect to a Supabase database, and Supabase requires you to turn on security rules explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in Create.xyz apps?",
             "Independent research auditing thousands of apps generated by AI coding tools has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my Create.xyz app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
        ]),
    },

    "tempo": {
        "title": "Is Your Tempo App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Tempo Labs app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your Tempo app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI tools like Tempo found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Tempo app security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Tempo safe to use?",
             "Tempo is a legitimate, widely used AI app builder built specifically around Supabase. The risk isn't the platform — it's that Supabase requires you to turn on security rules explicitly, and when that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in Tempo apps?",
             "Independent research auditing thousands of apps generated by AI coding tools has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my Tempo app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
        ]),
    },

    "softgen": {
        "title": "Is Your Softgen App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Softgen app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your Softgen app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI tools like Softgen found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Softgen app security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Softgen safe to use?",
             "Softgen is a legitimate AI app builder. The risk isn't the platform — it's that apps it generates often connect to a Supabase database, and Supabase requires you to turn on security rules explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in Softgen apps?",
             "Independent research auditing thousands of apps generated by AI coding tools has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my Softgen app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
        ]),
    },

    "same": {
        "title": "Is Your Same.new App Safe? Free Supabase Security Check",
        "meta_description": "Check if your Same.new app is exposing user data through Supabase. Free, read-only scan for the missing-security-policy issue found across AI-built apps.",
        "hero_h1": "Is your Same.new app safe? Find out in under a minute.",
        "hero_lede": "Independent research scanning thousands of apps built with AI tools like Same.new found that the large majority had at least one security flaw, most commonly a missing database permission rule. Paste your Supabase URL below to check your own app right now — free, read-only, no signup.",
        "faq_heading": "Same.new app security, answered plainly.",
        "faq_items": _build_faq([
            ("Is Same.new safe to use?",
             "Same.new is a legitimate AI app builder. The risk isn't the platform — it's that apps it generates often connect to a Supabase database, and Supabase requires you to turn on security rules explicitly. When that step is skipped, anyone can read the data through the app's own public connection."),
            ("How common is this problem in Same.new apps?",
             "Independent research auditing thousands of apps generated by AI coding tools has repeatedly found that the large majority had at least one confirmed security flaw, most often a database left readable to anyone without logging in."),
            ("How do I check if my Same.new app is exposed?",
             "Use the free scanner above. Paste your Supabase project URL and its public anon key (both are already visible in your app's own browser code, in Project Settings → API on Supabase). The scan checks, read-only, whether common tables and storage buckets are readable without logging in."),
            ("Does this touch my code or my users' data?",
             "No. The scan only reads what's already publicly reachable from any visitor's browser, never writes or modifies anything, and doesn't store the data values it finds — only whether a table responded and how sensitive the response looked."),
            ("Doesn't Supabase already have a free tool for this?",
             "Yes — Supabase's own Security Advisor (Database → Security Advisor in your project dashboard) checks for similar things, for free. The difference: it lives inside a technical dashboard and assumes you can read SQL and policy rules. This scan is built for everyone else — you paste two values you already have, get a plain-language answer, and if something's wrong, a ready-to-paste SQL fix. No dashboard, no SQL knowledge required."),
        ]),
    },

}
