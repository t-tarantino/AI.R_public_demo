# Deploy — AI.R (Render free + Supabase)

Prima pubblicazione privata: accesso solo via link + login dell'app. Un solo
servizio web (Docker) su Render serve sia le API sia la SPA React; i dati stanno
su un Postgres gestito su Supabase (con backup).

## 1. GitHub (una volta)
Render fa il deploy da un repo Git. Da `ai-r/`:

```
git add -A
git commit -m "Prepara deploy: serve SPA, cookie secure, Dockerfile, render.yaml"
```

Crea un repo **privato** su GitHub e collega il remote:

```
gh repo create ai-r --private --source . --remote origin --push
# oppure, senza gh CLI:
# git remote add origin https://github.com/<tuo-utente>/ai-r.git
# git push -u origin master
```

## 2. Supabase (database)
1. https://supabase.com → **New project** (scegli una region vicina, es. EU).
   Salva la **Database password** che imposti.
2. Project → **Connect** → tab **Session pooler** (NON "Transaction").
   Copia la URI: `postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres`
3. Cambia il prefisso `postgresql://` in **`postgresql+psycopg://`** e sostituisci
   `<password>` con la password del punto 1. Questa è la tua `DATABASE_URL`.

## 3. Render (hosting)
1. https://render.com → **New +** → **Blueprint** → collega il repo GitHub.
   Render legge `render.yaml` e crea il servizio Docker (piano **free**).
2. Nelle env vars del servizio imposta **`DATABASE_URL`** = la stringa del punto 2.
   (`SECRET_KEY` la genera Render da solo; `APP_ENV=production` e `COOKIE_SECURE=true`
   sono già nel blueprint.)
3. **Create** → Render builda l'immagine e all'avvio esegue `alembic upgrade head`
   (crea tutte le tabelle sul DB Supabase vuoto). Attendi lo stato **Live**.

## 4. Crea gli utenti (una volta)
Sul servizio Render → tab **Shell**:

```
python -m scripts.create_users
```

Crea un account per ogni worker (password iniziale `demo1234`). Poi ognuno cambia
la propria password dall'app (o tu passi `python -m scripts.create_users <nome> <password>`).

## 5. Condividi
URL del tipo `https://ai-r.onrender.com`. Manda **link + credenziali**
solo alle persone autorizzate. Nessuna indicizzazione pubblica; senza login non si
vede nulla.

---

### Note
- **Cold start (piano free):** dopo ~15 min di inattività il servizio si "addormenta";
  la prima richiesta successiva impiega ~40s, poi torna istantaneo. Per eliminarlo:
  passare il servizio a un piano a pagamento (~7$/mese).
- **Aggiornare l'app:** `git push` → Render ribuilda e rideploya da solo (le
  migrazioni girano automaticamente).
- **Dati storici (registro palloncini):** importabili dopo il primo deploy puntando
  gli script di import alla `DATABASE_URL` di Supabase.
```