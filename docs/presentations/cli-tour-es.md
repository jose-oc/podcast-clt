---
marp: true
theme: default
paginate: true
size: 16:9
title: podcast-ctl — Tour por la CLI
description: Presentación visual de la CLI podcast-ctl (español)
---

<style>
section {
  background: #0d1117;
  color: #e6edf3;
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  padding: 60px 70px;
  font-size: 30px;
  line-height: 1.45;
}
h1 { color: #58a6ff; font-size: 60px; letter-spacing: -1px; }
h2 { color: #58a6ff; font-size: 46px; margin-bottom: 18px; }
h3 { color: #7ee787; }
strong { color: #ffa657; }
code { background: #161b22; color: #7ee787; border-radius: 6px; padding: 2px 8px; }
pre { background: #161b22; border: 1px solid #30363d; border-radius: 12px; padding: 22px 26px; }
pre code { background: none; padding: 0; font-size: 26px; }
a { color: #58a6ff; }
table { font-size: 26px; background: transparent; }
th, td { background: #161b22; color: #e6edf3; }
th { background: #1c2530; }
th { color: #58a6ff; }
td, th { border-color: #30363d !important; }
section.lead { text-align: center; }
section.lead h1 { font-size: 84px; }
section.lead p { color: #9da7b3; font-size: 34px; }
section::after { color: #6e7681; font-size: 20px; }
.flow { display: flex; align-items: stretch; gap: 12px; margin: 24px 0; }
.flow .step {
  flex: 1; background: #161b22; border: 2px solid #30363d; border-radius: 14px;
  padding: 18px 14px; text-align: center; font-size: 25px;
}
.flow .step b { display: block; color: #58a6ff; font-size: 28px; margin-bottom: 6px; }
.flow .arrow { align-self: center; color: #ffa657; font-size: 40px; }
.tier { border-left: 6px solid; border-radius: 10px; background: #161b22;
  padding: 12px 20px; margin: 10px 0; font-size: 26px; }
.tier b { font-size: 28px; }
.t1 { border-color: #7ee787; } .t1 b { color: #7ee787; }
.t2 { border-color: #58a6ff; } .t2 b { color: #58a6ff; }
.t3 { border-color: #d2a8ff; } .t3 b { color: #d2a8ff; }
.t4 { border-color: #ffa657; } .t4 b { color: #ffa657; }
.cols { display: flex; gap: 40px; }
.cols > div { flex: 1; }
.small { font-size: 24px; color: #9da7b3; }
.tag { display: inline-block; background: #1f6feb33; border: 1px solid #1f6feb;
  color: #58a6ff; border-radius: 999px; padding: 2px 16px; font-size: 22px; margin-right: 8px; }
</style>

<!-- _class: lead -->

# 🎙️ podcast-ctl

**Tus pódcasts, transcritos y buscables**

Del audio de un episodio a una base de conocimiento lista para tu LLM — con una sola CLI.

<!--
Guion: esta es la herramienta que presentamos. En una frase: encuentra
episodios de pódcasts, los transcribe de la forma más barata y privada
posible, y los convierte en una base de conocimiento que puedes consultar
o pasar a cualquier LLM.
-->

---

## El problema

- Contenido buenísimo **encerrado en audio** — horas y horas
- Sin búsqueda, sin citas, sin forma de preguntar *"¿qué dijeron sobre X?"*
- Transcribir en la nube se pone **caro** muy rápido
- Y mandarlo todo a una API externa no es ideal en **privacidad**

---

## Qué hace podcast-ctl

<div class="flow">
  <div class="step"><b>🔍 Descubre</b>Busca en el catálogo de Apple Podcasts</div>
  <div class="arrow">→</div>
  <div class="step"><b>Inspecciona</b>Chequeo previo: trabajo y coste previstos</div>
  <div class="arrow">→</div>
  <div class="step"><b>Transcribe</b>4 niveles en cascada, el más barato primero</div>
  <div class="arrow">→</div>
  <div class="step"><b>Base de conocimiento</b>Markdown + búsqueda híbrida</div>
  <div class="arrow">→</div>
  <div class="step"><b>Pregunta</b>Cualquier LLM — local o en la nube</div>
</div>

Como entrada vale un **feed RSS**, el **título del programa**, un **enlace de YouTube** o un **archivo de audio local**.

---

## Instalar y ejecutar

```bash
git clone https://github.com/jose-oc/podcast-ctl.git
cd podcast-ctl
uv run podcast-ctl --help
```

- Gestionado con **uv** — sin configurar entornos a mano
- Nivel Whisper local opcional: `uv sync --extra whisper`
- Los niveles en la nube usan `GROQ_API_KEY` / `OPENAI_API_KEY`

---

## Seis comandos

| Comando | Qué hace |
| :--- | :--- |
| `search` | Encontrar programas en el catálogo de Apple Podcasts |
| `inspect` | Chequeo previo — antes de gastar nada |
| `transcribe` | Transcribir episodios, vídeos o archivos locales |
| `mapping` | Enseñar las relaciones programa ↔ canal de YouTube |
| `cache` | Gestionar la caché local de transcripciones |
| `kb` | Construir y consultar la base de conocimiento |

---

## 1 · Descubrir

```bash
podcast-ctl search "Latent Space"
```

- Selector interactivo sobre el catálogo de Apple Podcasts / iTunes
- O sáltate el descubrimiento: pasa un **feed**, un **título**, una **URL de YouTube** o un **archivo** directamente a los demás comandos

<p class="small">podcast-ctl search "Huberman Lab" --limit 5 --no-interactive</p>

---

## 2 · Inspeccionar: mira antes de saltar

```bash
podcast-ctl inspect "https://feeds.simplecast.com/82GLSDrl"
```

El **gatekeeper** responde, *antes* de transcribir nada:

- Cuántos episodios, cuánto audio, cuánto disco
- A qué **nivel** se resuelve cada episodio
- Cuánto va a costar — en tiempo y en dinero

---

## 3 · Transcribir

```bash
# Último episodio de un programa
podcast-ctl transcribe "Latent Space"

# Un episodio concreto, todo en local
podcast-ctl transcribe "Latent Space" -e "Ilya Sutskever" --model-size small

# Una grabación local, todos los formatos
podcast-ctl transcribe ./meeting.m4a -o ./notas --format all
```

`-e` acepta el **número de episodio publicado**, un trozo del título, un ID — o `-e 1` para el más reciente.

---

## Elige exactamente los episodios que quieres

```bash
podcast-ctl transcribe "Marketing Online" --episodes 2890,2894,2901
podcast-ctl transcribe "Marketing Online" --episodes 2890..2900
podcast-ctl transcribe "Marketing Online" --match "Kubernetes|Talos"
podcast-ctl transcribe "Marketing Online" --since 2026-01-01 --until 2026-03-31
podcast-ctl transcribe "Marketing Online" --pick
```

- Los filtros se **combinan** (AND): `--episodes 2800..2900 --match "SEO"`
- Toda selección muestra una **tabla de confirmación** — número, fecha, título y duración — *antes* de transcribir nada

---

## El corazón: cascada de 4 niveles

<div class="tier t1"><b>Nivel 1 · Transcripciones del RSS</b> — etiquetas oficiales de Podcasting 2.0. Instantáneo y gratis.</div>
<div class="tier t2"><b>Nivel 2 · Subtítulos de YouTube</b> — gracias a las relaciones programa ↔ canal aprendidas. Instantáneo y gratis.</div>
<div class="tier t3"><b>Nivel 3 · Whisper local</b> — faster-whisper en tu GPU/CPU. Privado y gratis.</div>
<div class="tier t4"><b>Nivel 4 · APIs en la nube</b> — Whisper de Groq / OpenAI. Rápido, con guardarraíles de coste interactivos.</div>

**Gana la fuente más barata y privada — automáticamente.** Las transcripciones se guardan en SQLite, así que nunca pagas dos veces.

---

## Formatos de salida para cada uso

```bash
podcast-ctl transcribe "Hardcore History" --latest 3 --format all --yes
```

<div class="cols">
<div>

- **Markdown** — con estilo y frontmatter YAML
- **Prosa** — `.txt` limpio y legible
- **SRT / VTT** — archivos de subtítulos

</div>
<div>

- **JSON** — datos estructurados
- `--format both` (por defecto): `.md` + `.txt`
- Combina a tu gusto: `--format markdown,srt,json`

</div>
</div>

---

## Caché y mappings: la CLI aprende

<div class="cols">
<div>

### `cache`
```bash
podcast-ctl cache stats
podcast-ctl cache list
podcast-ctl cache clean --yes
```
Cada transcripción se guarda en local — repetir es instantáneo.

</div>
<div>

### `mapping`
```bash
podcast-ctl mapping list
podcast-ctl mapping add show <feed_url> <youtube_channel_url>
```
Vincular un programa con su canal de YouTube desbloquea los **subtítulos gratis del Nivel 2**.

</div>
</div>

---

## 4 · Construir la base de conocimiento

```bash
podcast-ctl kb build
```

```
kb/
  raw/<show>/<episode>.json      # copias fuente inmutables
  episodes/<show>/<episode>.md   # Markdown limpio por episodio
  INDEX.md                       # catálogo navegable
  db/kb.sqlite                   # índice de búsqueda FTS5 por fragmentos
```

**Incremental**: los episodios sin cambios se saltan. **Reproducible**: todo deriva de `raw/` — borra y reconstruye cuando quieras.

---

## Búscala — con citas

```bash
podcast-ctl kb search "vector databases" --limit 5
podcast-ctl kb search "búsqueda semántica" --context
podcast-ctl kb search "precios" --json
```

- **FTS5 + BM25** de SQLite, insensible a mayúsculas y diacríticos
- Cada resultado cita **`[Episode @ mm:ss]`** — vuelve al audio en el punto exacto
- `--context` imprime bloques Markdown listos para pegar en un LLM; `--json` es para scripts

---

## Búscala por significado — embeddings + híbrida

```bash
podcast-ctl kb embed                               # un vector por fragmento, incremental
podcast-ctl kb search "dolor de hombro"            # también encuentra "molestias en el trapecio"
podcast-ctl kb search "dolor de hombro" --mode lexical  # solo palabras literales
```

- La búsqueda léxica (FTS5/BM25) encuentra **palabras literales**; los vectores encuentran **significado**
- **Híbrida** fusiona ambos rankings con Reciprocal Rank Fusion (RRF) — mejor que cada una por separado
- `--mode auto` (por defecto): híbrida si ya hay embeddings, léxica si no

<!--
Guion: la búsqueda léxica se pierde las paráfrasis — "dolor de hombro" no
casa con un episodio que dice "molestias en el trapecio". kb embed convierte
cada fragmento en un vector de su significado, y las paráfrasis casan. La
híbrida ejecuta ambas búsquedas y fusiona los rankings con RRF; la columna
Sources muestra cuál rankeó cada resultado. Prueba la misma consulta con
--mode lexical y sin él — la diferencia vende la función.
-->

---

## Vectores en local, cero acoplamiento

- Modelo por defecto: **BAAI/bge-m3** con sentence-transformers — multilingüe potente (español incluido)
- **Privado y gratis**: sin coste por consulta, los transcripts no salen de tu máquina
- Coste único: torch + descarga de **~2 GB** del modelo; ~4 KB por fragmento en disco
- Los vectores son blobs en el mismo `kb.sqlite` — coseno **exacto** en proceso, sin servicio de BD vectorial
- Adaptador de nube opcional por variables de entorno: `PODCAST_CTL_EMBED_BASE_URL` / `_API_KEY` / `_MODEL`
- Cambia de modelo o proveedor → `podcast-ctl kb embed --reindex`

<!--
Guion: ¿de dónde salen los vectores? De un modelo local, bge-m3, bueno en
español, sin API key ni coste por consulta. Los ~2 GB y torch son un coste
único, y ambos solo *generan* vectores; compararlos después es aritmética.
¿Por qué no una BD vectorial? A esta escala el coseno exacto en proceso tarda
milisegundos y encuentra los vecinos reales; los índices aproximados (HNSW)
compensan a partir de millones de vectores. Si llegamos, sqlite-vec reutiliza
los mismos vectores guardados. Explicación completa: docs/HYBRID_SEARCH.md.
-->

---

## 5 · Pregunta a un LLM — *tu* LLM

La KB no te ata a ningún proveedor:

<div class="cols">
<div>

### 🏠 Todo en local
`kb search --json` → pasa los fragmentos a **Ollama**. Nada sale de tu máquina.

</div>
<div>

### ☁️ Cualquier chat en la nube
`kb search --context` → pégalo en ChatGPT, Claude, Gemini… sin cambios.

</div>
<div>

### NotebookLM
Sube los `episodes/*.md` como fuentes. Las marcas de tiempo sobreviven como texto.

</div>
</div>

---

## 5b · La cuarta vía: un agente con shell

Los agentes de IA de escritorio (Codex, Claude Code, Hermes…) no necesitan que copies y pegues — manejan la CLI ellos mismos:

- El repo incluye **`AGENTS.md`** y **`skills/podcast-clt/SKILL.md`**: Markdown plano que le enseña los comandos a cualquier agente
- El agente ejecuta `kb search --json` y recibe **solo los fragmentos relevantes**, con citas — crezca lo que crezca la KB
- Retrieval determinista, **cualquier proveedor**: el modelo lo eliges tú

```bash
podcast-ctl kb search "vector databases" --json --limit 5
```

<!--
Guion: copiar y pegar y NotebookLM no escalan, y Ollama requiere un script.
Un agente con shell ejecuta el bucle de retrieval él solo: busca, lee los
fragmentos y vuelve a buscar si la respuesta no está. AGENTS.md es la
convención que leen la mayoría de coding agents al entrar en un repo; el
SKILL.md es la misma guía en formato skill. Cero acoplamiento — es Markdown
plano.
-->

---

## Principios de diseño

<span class="tag">Coste primero</span> <span class="tag">Privacidad primero</span> <span class="tag">Sin atarse a proveedores</span>

- Mostrar siempre el trabajo **antes** de pedir confirmación
- Gana la fuente más barata; la caché evita trabajo duplicado
- Whisper y LLMs locales: todo se queda en tu máquina
- Salida en Markdown y JSON planos — **cero lock-in**

---

<!-- _class: lead -->

# Pruébalo

```bash
uv run podcast-ctl --help
```

**github.com/jose-oc/podcast-clt** · Licencia MIT

Documentación: `README.md` · `AGENTS.md` · `docs/CLI_REFERENCE.md` · `docs/KNOWLEDGE_BASE.md` · `docs/HYBRID_SEARCH.md`

<!--
Guion: clónalo, transcribe un episodio, construye la KB y hazle una
pregunta. Con uv el quickstart son minutos.
-->
