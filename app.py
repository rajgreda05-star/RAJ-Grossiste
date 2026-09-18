import os
import io
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from fpdf import FPDF

# ------------------------------------------------------------------
# CONFIGURATION GENERALE & COORDONNEES GROSSISTE
# ------------------------------------------------------------------
DATA_DIR = "data"
PRODUITS_FILE = os.path.join(DATA_DIR, "produits.csv")
CLIENTS_FILE = os.path.join(DATA_DIR, "clients.csv")
VENTES_FILE = os.path.join(DATA_DIR, "ventes.csv")
ACHATS_FILE = os.path.join(DATA_DIR, "achats.csv")

# Informations du Grossiste
NOM_ENTREPRISE = "RAJ-grossiste"
TEL_ENTREPRISE = "032 29 958 92"
VILLE_ENTREPRISE = "Diego"
QUARTIER_ENTREPRISE = "Lazaret-Sud lot 200LE bus"

SEUIL_STOCK_FAIBLE = 20                    # alerte rupture de stock
JOUR_REPOS = 6                              # 0=lundi ... 6=dimanche

MOT_DE_PASSE = ""

PALIERS_REMISE = [
    (0, 0),
    (10, 2),
    (50, 5),
    (100, 10),
]

st.set_page_config(page_title="Gestion RAJ-grossiste", page_icon="🧾", layout="wide")
os.makedirs(DATA_DIR, exist_ok=True)


# ------------------------------------------------------------------
# INITIALISATION DES FICHIERS DE DONNEES
# ------------------------------------------------------------------
def init_files():
    if not os.path.exists(PRODUITS_FILE):
        pd.DataFrame(
            columns=["ID_Produit", "Nom_Produit", "PU_Ar", "Unite", "Stock"]
        ).to_csv(PRODUITS_FILE, index=False)
    if not os.path.exists(CLIENTS_FILE):
        pd.DataFrame(
            columns=["ID_Client", "Nom_Client", "Contact"]
        ).to_csv(CLIENTS_FILE, index=False)
    if not os.path.exists(VENTES_FILE):
        pd.DataFrame(
            columns=[
                "ID_Vente", "DateHeure", "ID_Client", "Nom_Client",
                "ID_Produit", "Nom_Produit", "PU", "Quantite",
                "Remise_pct", "Montant", "Mode_Paiement",
            ]
        ).to_csv(VENTES_FILE, index=False)
    if not os.path.exists(ACHATS_FILE):
        pd.DataFrame(
            columns=[
                "ID_Achat", "DateHeure", "Element", "Prix_Achat",
                "Transport", "Autre1", "Autre2", "Montant_Total",
            ]
        ).to_csv(ACHATS_FILE, index=False)


init_files()


# ------------------------------------------------------------------
# FONCTIONS UTILITAIRES : CHARGEMENT / SAUVEGARDE
# ------------------------------------------------------------------
def load_produits():
    return pd.read_csv(PRODUITS_FILE, dtype={"ID_Produit": str})


def save_produits(df):
    df.to_csv(PRODUITS_FILE, index=False)


def load_clients():
    return pd.read_csv(CLIENTS_FILE, dtype={"ID_Client": str})


def save_clients(df):
    df.to_csv(CLIENTS_FILE, index=False)


def load_ventes():
    df = pd.read_csv(VENTES_FILE, dtype={"ID_Vente": str, "ID_Client": str, "ID_Produit": str})
    if not df.empty:
        df["DateHeure"] = pd.to_datetime(df["DateHeure"])
    return df


def save_ventes(df):
    df.to_csv(VENTES_FILE, index=False)


def load_achats():
    df = pd.read_csv(ACHATS_FILE, dtype={"ID_Achat": str})
    if not df.empty:
        df["DateHeure"] = pd.to_datetime(df["DateHeure"])
    return df


def save_achats(df):
    df.to_csv(ACHATS_FILE, index=False)


def prochain_id(df, colonne, prefixe):
    if df.empty:
        return f"{prefixe}0001"
    nums = df[colonne].astype(str).str.replace(prefixe, "", regex=False)
    nums = pd.to_numeric(nums, errors="coerce").fillna(0)
    return f"{prefixe}{int(nums.max()) + 1:04d}"


def calcul_remise(qte):
    pct = 0
    for seuil, remise in sorted(PALIERS_REMISE, key=lambda x: x[0]):
        if qte >= seuil:
            pct = remise
    return pct


# ------------------------------------------------------------------
# RECONNAISSANCE AUTOMATIQUE DES NOMS DE COLONNES
# ------------------------------------------------------------------
ALIAS_COLONNES = {
    "ID_Produit": ["id_produit", "idproduit", "id_prod", "id"],
    "Nom_Produit": ["nom_produit", "nomproduit", "nom_prod", "produit", "designation", "nom"],
    "PU_Ar": [
        "pu_ar", "p_u_ar", "pu", "p_u", "prix_unitaire", "prix_unitaire_ar",
        "prixunitaire", "prix", "pu_ariary",
    ],
    "Stock": [
        "stock", "quantite_totale", "quantitetotale", "qte_totale",
        "qtetotale", "quantite_total", "quantite", "qte", "quantite_disponible",
    ],
    "Unite": ["unite", "unit", "unites"],
}


def normaliser_nom(col):
    col = str(col).strip().lower()
    col = unicodedata.normalize("NFKD", col).encode("ascii", "ignore").decode("ascii")
    col = col.replace(" ", "_").replace("-", "_")
    while "__" in col:
        col = col.replace("__", "_")
    return col


def reconnaitre_colonnes(df):
    mapping = {}
    for col in df.columns:
        clean = normaliser_nom(col)
        for standard, alias_list in ALIAS_COLONNES.items():
            if clean in alias_list and col != standard:
                mapping[col] = standard
                break
    if mapping:
        df = df.rename(columns=mapping)
    return df, mapping


# ------------------------------------------------------------------
# GENERATION DE FACTURE PDF (Avec Marge optimisée et Numéro Facture)
# ------------------------------------------------------------------
class FacturePDF(FPDF):
    def __init__(self, format_page="A4"):
        super().__init__(format=format_page)
        # Marges suffisantes pour éviter les coupures de texte
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("Helvetica", "B", 13)
        self.cell(0, 6, NOM_ENTREPRISE, ln=1, align="C")
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, f"Tél : {TEL_ENTREPRISE} | Ville : {VILLE_ENTREPRISE}", ln=1, align="C")
        self.cell(0, 5, f"Quartier : {QUARTIER_ENTREPRISE}", ln=1, align="C")
        self.ln(2)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 6, "FACTURE DE VENTE", ln=1, align="C")
        self.ln(3)


def generer_facture_pdf(items_df, client_nom, num_facture, total, mode_paiement, date_vente=None, format_page="A4"):
    pdf = FacturePDF(format_page=format_page)
    pdf.add_page()
    
    if date_vente is None:
        date_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    else:
        date_str = pd.to_datetime(date_vente).strftime('%d/%m/%Y %H:%M')

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, f"N° Facture : {num_facture}", ln=1)
    pdf.cell(0, 5, f"Date       : {date_str}", ln=1)
    pdf.cell(0, 5, f"Client     : {client_nom}", ln=1)
    pdf.cell(0, 5, f"Paiement   : {mode_paiement}", ln=1)
    pdf.ln(4)

    # Marges adaptées selon A4 ou A5
    if format_page == "A5":
        largeurs = [40, 20, 12, 14, 15, 25]
    else:
        largeurs = [60, 25, 18, 20, 20, 32]

    entetes = ["Produit", "PU (Ar)", "Qte", "Unite", "Remise", "Montant (Ar)"]
    pdf.set_font("Helvetica", "B", 8)
    for w, h in zip(largeurs, entetes):
        pdf.cell(w, 6, h, border=1, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for _, row in items_df.iterrows():
        # Tronquage du texte si trop long pour éviter les débordements
        nom_prod = str(row["Nom_Produit"])
        max_chars = 25 if format_page == "A5" else 35
        if len(nom_prod) > max_chars:
            nom_prod = nom_prod[:max_chars-2] + ".."

        pdf.cell(largeurs[0], 6, nom_prod, border=1)
        pdf.cell(largeurs[1], 6, f"{row['PU']:,.0f}", border=1, align="R")
        pdf.cell(largeurs[2], 6, str(row["Quantite"]), border=1, align="C")
        pdf.cell(largeurs[3], 6, str(row.get("Unite", "")), border=1, align="C")
        pdf.cell(largeurs[4], 6, f"{row['Remise_pct']}%", border=1, align="C")
        pdf.cell(largeurs[5], 6, f"{row['Montant']:,.0f}", border=1, align="R")
        pdf.ln()

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(sum(largeurs[:-1]), 7, "TOTAL", border=1, align="R")
    pdf.cell(largeurs[-1], 7, f"{total:,.0f} Ar", border=1, align="R")
    pdf.ln(12)
    pdf.cell(0, 5, "Signature & Cachet :", ln=1)

    return bytes(pdf.output())


# ------------------------------------------------------------------
# AUTHENTIFICATION
# ------------------------------------------------------------------
def verifier_acces():
    if not MOT_DE_PASSE:
        return True
    if "authentifie" not in st.session_state:
        st.session_state["authentifie"] = False
    if st.session_state["authentifie"]:
        return True
    st.title("🔒 Accès protégé")
    mdp = st.text_input("Mot de passe", type="password")
    if st.button("Se connecter"):
        if mdp == MOT_DE_PASSE:
            st.session_state["authentifie"] = True
            st.rerun()
        else:
            st.error("Mot de passe incorrect.")
    return False


if not verifier_acces():
    st.stop()


# ------------------------------------------------------------------
# NAVIGATION
# ------------------------------------------------------------------
st.sidebar.title(f"🧾 {NOM_ENTREPRISE}")

produits_dispo = load_produits()
aucun_produit = produits_dispo.empty

if aucun_produit:
    st.sidebar.error("⚠️ Aucun produit importé.")
    page = "🏷️ Produits"
    st.sidebar.caption("Importez d'abord votre fichier produits pour débloquer les autres pages.")
else:
    page = st.sidebar.radio(
        "Navigation",
        ["🏷️ Produits", "🛒 Vente", "📦 Achat", "📊 Suivi des ventes", "📈 Analyse"],
    )

if datetime.now().weekday() == JOUR_REPOS:
    st.sidebar.warning("⚠️ Aujourd'hui est le jour de repos habituel (dimanche).")


# ------------------------------------------------------------------
# PAGE 1 : PRODUITS
# ------------------------------------------------------------------
if page == "🏷️ Produits":
    st.header("🏷️ Gestion des produits")

    produits = load_produits()

    if produits.empty:
        st.warning("📭 Aucun produit n'est encore importé.")
    else:
        st.success(f"✅ {len(produits)} produit(s) actuellement enregistré(s).")

    st.subheader("📥 Importer votre liste de produits (Excel ou CSV)")
    fichiers = st.file_uploader(
        "Fichier(s) produits (.csv ou .xlsx)",
        type=["csv", "xlsx"],
        accept_multiple_files=True,
    )

    if fichiers:
        morceaux = []
        erreur = False
        for fichier in fichiers:
            if fichier.name.endswith(".csv"):
                nouveau = pd.read_csv(fichier, dtype=str)
            else:
                nouveau = pd.read_excel(fichier, dtype=str)

            nouveau, mapping = reconnaitre_colonnes(nouveau)

            colonnes_attendues = {"ID_Produit", "Nom_Produit", "PU_Ar"}
            if not colonnes_attendues.issubset(set(nouveau.columns)):
                manquantes = colonnes_attendues - set(nouveau.columns)
                st.error(f"Le fichier « {fichier.name} » requiert : {manquantes}.")
                erreur = True
                continue

            nouveau["ID_Produit"] = nouveau["ID_Produit"].astype(str)
            nouveau["PU_Ar"] = pd.to_numeric(nouveau["PU_Ar"], errors="coerce").fillna(0)
            if "Unite" not in nouveau.columns:
                nouveau["Unite"] = ""
            if "Stock" not in nouveau.columns:
                nouveau["Stock"] = 0
            else:
                nouveau["Stock"] = pd.to_numeric(nouveau["Stock"], errors="coerce").fillna(0)
            morceaux.append(nouveau[["ID_Produit", "Nom_Produit", "PU_Ar", "Unite", "Stock"]])

        if morceaux and not erreur:
            nouveau_total = pd.concat(morceaux, ignore_index=True).drop_duplicates(
                subset="ID_Produit", keep="last"
            )
            st.write(f"➡️ {len(nouveau_total)} produit(s) prêt(s) à être importé(s).")
            mode = st.radio(
                "Mode d'import",
                ["Remplacer la liste actuelle", "Ajouter / mettre à jour la liste actuelle"],
            )
            if st.button("✅ Valider l'import", type="primary"):
                if mode == "Remplacer la liste actuelle":
                    save_produits(nouveau_total)
                else:
                    fusion = pd.concat([produits, nouveau_total], ignore_index=True).drop_duplicates(
                        subset="ID_Produit", keep="last"
                    )
                    save_produits(fusion)
                st.success("Import effectué avec succès.")
                st.rerun()

    if not produits.empty:
        st.subheader("🔎 Voir et éditer les produits existants")
        recherche_prod = st.text_input("Rechercher un produit (nom ou ID)")
        produits_affiches = produits.copy()
        if recherche_prod:
            masque = (
                produits_affiches["Nom_Produit"].str.contains(recherche_prod, case=False, na=False)
                | produits_affiches["ID_Produit"].str.contains(recherche_prod, case=False, na=False)
            )
            produits_affiches = produits_affiches[masque]

        produits_edit = st.data_editor(
            produits_affiches,
            num_rows="dynamic",
            use_container_width=True,
            key="editeur_produits",
        )
        if st.button("💾 Enregistrer les modifications produits"):
            base = produits.set_index("ID_Produit")
            modif = produits_edit.set_index("ID_Produit")
            base.update(modif)
            base = pd.concat([base, modif[~modif.index.isin(base.index)]])
            save_produits(base.reset_index())
            st.success("Produits mis à jour.")
            st.rerun()

        stock_faible = produits_edit[produits_edit["Stock"] < SEUIL_STOCK_FAIBLE]
        if not stock_faible.empty:
            st.warning(f"⚠️ {len(stock_faible)} produit(s) en stock faible (< {SEUIL_STOCK_FAIBLE})")
            st.dataframe(stock_faible, use_container_width=True)


# ------------------------------------------------------------------
# PAGE 2 : VENTE (AVEC N° FACTURE & FLUX VALIDER PUIS TÉLÉCHARGER)
# ------------------------------------------------------------------
elif page == "🛒 Vente":
    st.header("🛒 Nouvelle vente")

    produits = load_produits()
    clients = load_clients()

    if produits.empty:
        st.info("Veuillez d'abord importer votre liste de produits.")
        st.stop()

    col_client1, col_client2 = st.columns([2, 1])
    with col_client1:
        noms_clients = ["Client de passage"] + clients["Nom_Client"].tolist()
        client_choisi = st.selectbox("Client", noms_clients)
    with col_client2:
        mode_paiement = st.selectbox("Mode de paiement", ["Espèces", "Mobile Money", "Crédit"])

    with st.expander("➕ Ajouter un nouveau client"):
        nouveau_nom = st.text_input("Nom du client")
        nouveau_contact = st.text_input("Contact")
        if st.button("Ajouter ce client"):
            if nouveau_nom:
                nid = prochain_id(clients, "ID_Client", "C")
                clients = pd.concat(
                    [clients, pd.DataFrame([{"ID_Client": nid, "Nom_Client": nouveau_nom, "Contact": nouveau_contact}])],
                    ignore_index=True,
                )
                save_clients(clients)
                st.success("Client ajouté.")
                st.rerun()

    st.subheader("1. Sélectionner les produits vendus")
    recherche = st.text_input("🔎 Rechercher un produit (nom ou ID)")
    liste = produits.copy()
    if recherche:
        masque = (
            liste["Nom_Produit"].str.contains(recherche, case=False, na=False)
            | liste["ID_Produit"].str.contains(recherche, case=False, na=False)
        )
        liste = liste[masque]

    liste = liste.copy()
    liste.insert(0, "Sélection", False)
    liste["Quantité"] = 0

    liste_edit = st.data_editor(
        liste[["Sélection", "ID_Produit", "Nom_Produit", "PU_Ar", "Unite", "Stock", "Quantité"]],
        use_container_width=True,
        hide_index=True,
        key="editeur_vente",
        column_config={
            "Sélection": st.column_config.CheckboxColumn(required=True),
            "Quantité": st.column_config.NumberColumn(min_value=0, step=1),
        },
        disabled=["ID_Produit", "Nom_Produit", "PU_Ar", "Unite", "Stock"],
    )

    panier = liste_edit[(liste_edit["Sélection"]) & (liste_edit["Quantité"] > 0)].copy()

    if not panier.empty:
        st.subheader("2. Récapitulatif de la vente")
        panier["Remise_pct"] = panier["Quantité"].apply(calcul_remise)
        panier["Montant"] = (
            panier["PU_Ar"] * panier["Quantité"] * (1 - panier["Remise_pct"] / 100)
        ).round(0)
        panier_affiche = panier.rename(columns={"Quantité": "Quantite", "PU_Ar": "PU"})[
            ["ID_Produit", "Nom_Produit", "PU", "Quantite", "Unite", "Remise_pct", "Montant"]
        ]
        st.dataframe(panier_affiche, use_container_width=True)

        total = panier_affiche["Montant"].sum()
        st.markdown(f"### 💰 Total : {total:,.0f} Ar")

        # Alerte stock
        manque = panier.merge(produits, on="ID_Produit", suffixes=("", "_stock"))
        rupture = manque[manque["Quantité"] > manque["Stock"]]
        if not rupture.empty:
            st.error("⚠️ Stock insuffisant pour : " + ", ".join(rupture["Nom_Produit"].tolist()))

        format_facture = st.radio("Format de la facture PDF", ["A4", "A5"], horizontal=True)

        # BOUTON 1 : ENREGISTRER LA VENTE D'ABORD
        if st.button("💾 Enregistrer la vente", type="primary"):
            ventes = load_ventes()
            id_client = "0000" if client_choisi == "Client de passage" else clients.loc[
                clients["Nom_Client"] == client_choisi, "ID_Client"
            ].values[0]
            
            # Un seul ID_Vente unique pour toute la facture
            id_facture = prochain_id(ventes, "ID_Vente", "FAC-")
            date_heure_now = datetime.now()

            lignes = []
            for _, r in panier_affiche.iterrows():
                lignes.append({
                    "ID_Vente": id_facture,
                    "DateHeure": date_heure_now.strftime("%Y-%m-%d %H:%M:%S"),
                    "ID_Client": id_client,
                    "Nom_Client": client_choisi,
                    "ID_Produit": r["ID_Produit"],
                    "Nom_Produit": r["Nom_Produit"],
                    "PU": r["PU"],
                    "Quantite": r["Quantite"],
                    "Remise_pct": r["Remise_pct"],
                    "Montant": r["Montant"],
                    "Mode_Paiement": mode_paiement,
                })
                # Ajustement stock
                produits.loc[produits["ID_Produit"] == r["ID_Produit"], "Stock"] -= r["Quantite"]

            ventes = pd.concat([ventes, pd.DataFrame(lignes)], ignore_index=True)
            save_ventes(ventes)
            save_produits(produits)

            # Mettre en mémoire la dernière vente pour le téléchargement PDF
            st.session_state["derniere_vente"] = {
                "id_facture": id_facture,
                "panier": panier_affiche,
                "client": client_choisi,
                "total": total,
                "mode_paiement": mode_paiement,
                "date": date_heure_now,
                "format": format_facture
            }
            st.success(f"Vente enregistrée avec succès ! N° Facture : {id_facture} ✅")

    # BOUTON 2 : TÉLÉCHARGER LA FACTURE APRÈS ENREGISTREMENT
    if "derniere_vente" in st.session_state:
        st.divider()
        st.subheader("3. Télécharger la facture")
        dv = st.session_state["derniere_vente"]
        st.info(f"Facture prête pour l'enregistrement N° **{dv['id_facture']}**")
        
        pdf_bytes = generer_facture_pdf(
            items_df=dv["panier"],
            client_nom=dv["client"],
            num_facture=dv["id_facture"],
            total=dv["total"],
            mode_paiement=dv["mode_paiement"],
            date_vente=dv["date"],
            format_page=dv["format"]
        )
        st.download_button(
            "📄 Télécharger la facture PDF",
            data=pdf_bytes,
            file_name=f"Facture_{dv['id_facture']}.pdf",
            mime="application/pdf",
        )
    else:
        if panier.empty:
            st.info("Cochez au moins un produit et indiquez une quantité pour continuer.")


# ------------------------------------------------------------------
# PAGE 3 : ACHAT
# ------------------------------------------------------------------
elif page == "📦 Achat":
    st.header("📦 Nouvel achat")

    with st.form("form_achat"):
        element = st.text_input("Élément acheté")
        prix_achat = st.number_input("Prix d'achat (Ar)", min_value=0.0, step=100.0)
        transport = st.number_input("Transport (Ar)", min_value=0.0, step=100.0)
        autre1 = st.number_input("Autre frais 1 (Ar)", min_value=0.0, step=100.0)
        autre2 = st.number_input("Autre frais 2 (Ar)", min_value=0.0, step=100.0)
        valider = st.form_submit_button("💾 Enregistrer l'achat")

    total_achat = prix_achat + transport + autre1 + autre2
    st.markdown(f"**Montant total : {total_achat:,.0f} Ar**")

    if valider:
        if not element:
            st.error("Veuillez indiquer l'élément acheté.")
        else:
            achats = load_achats()
            id_achat = prochain_id(achats, "ID_Achat", "A")
            nouvelle_ligne = {
                "ID_Achat": id_achat,
                "DateHeure": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "Element": element,
                "Prix_Achat": prix_achat,
                "Transport": transport,
                "Autre1": autre1,
                "Autre2": autre2,
                "Montant_Total": total_achat,
            }
            achats = pd.concat([achats, pd.DataFrame([nouvelle_ligne])], ignore_index=True)
            save_achats(achats)
            st.success("Achat enregistré ✅")
            st.rerun()

    st.subheader("Historique des achats")
    achats = load_achats()
    st.dataframe(achats, use_container_width=True)
    if not achats.empty:
        st.markdown(f"**Total des achats enregistrés : {achats['Montant_Total'].sum():,.0f} Ar**")


# ------------------------------------------------------------------
# PAGE 4 : SUIVI DES VENTES
# ------------------------------------------------------------------
elif page == "📊 Suivi des ventes":
    st.header("📊 Suivi des ventes")

    ventes = load_ventes()
    if ventes.empty:
        st.info("Aucune vente enregistrée pour le moment.")
        st.stop()

    col1, col2, col3 = st.columns(3)
    with col1:
        date_debut = st.date_input("Date début", ventes["DateHeure"].min().date())
    with col2:
        date_fin = st.date_input("Date fin", ventes["DateHeure"].max().date())
    with col3:
        client_filtre = st.selectbox("Client", ["Tous"] + sorted(ventes["Nom_Client"].unique().tolist()))

    produit_filtre = st.selectbox("Produit", ["Tous"] + sorted(ventes["Nom_Produit"].unique().tolist()))

    filtre = (ventes["DateHeure"].dt.date >= date_debut) & (ventes["DateHeure"].dt.date <= date_fin)
    if client_filtre != "Tous":
        filtre &= ventes["Nom_Client"] == client_filtre
    if produit_filtre != "Tous":
        filtre &= ventes["Nom_Produit"] == produit_filtre

    resultat = ventes[filtre].sort_values("DateHeure", ascending=False)
    st.dataframe(resultat, use_container_width=True)

    st.markdown(f"### 💰 Total sur la période : {resultat['Montant'].sum():,.0f} Ar")
    st.markdown(f"Nombre de lignes de vente : {len(resultat)}")

    csv_export = resultat.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Exporter en CSV", data=csv_export, file_name="suivi_ventes.csv", mime="text/csv")


# ------------------------------------------------------------------
# PAGE 5 : ANALYSE (AMÉLIORÉE : HEURES, SAISONS, FILTRES AVANCÉS)
# ------------------------------------------------------------------
elif page == "📈 Analyse":
    st.header("📈 Analyse avancée des ventes")

    ventes = load_ventes()
    if ventes.empty:
        st.info("Aucune vente enregistrée pour le moment.")
        st.stop()

    # Enrichissement automatique des données temporelles
    ventes["Date"] = ventes["DateHeure"].dt.date
    ventes["Heure"] = ventes["DateHeure"].dt.hour
    ventes["Annee"] = ventes["DateHeure"].dt.year
    ventes["Mois"] = ventes["DateHeure"].dt.month
    ventes["Semaine"] = ventes["DateHeure"].dt.isocalendar().week

    # Classification par moment de la journée
    def classifier_moment(heure):
        if heure < 12:
            return "Matin (Avant 12h)"
        elif 12 <= heure <= 14:
            return "Midi (12h - 14h)"
        else:
            return "Après-midi (Après 14h)"

    ventes["Moment_Journee"] = ventes["Heure"].apply(classifier_moment)

    # Classification par saison / fête (Adapté à Madagascar)
    def classifier_saison(row):
        mois = row["Mois"]
        jour = row["DateHeure"].day
        if mois == 12 and jour >= 20 or (mois == 1 and jour <= 5):
            return "🎉 Fêtes (Bonne Année / Noël)"
        elif mois in [12, 1, 2, 3]:
            return "🌧️ Saison chaude & pluies"
        elif mois in [4, 5]:
            return "🌸 Inter-saison / Automne"
        elif mois in [6, 7, 8]:
            return "❄️ Saison fraîche / Hiver"
        else:
            return "☀️ Saison sèche / Printemps"

    ventes["Saison"] = ventes.apply(classifier_saison, axis=1)

    # KPI principaux
    ca_total = ventes["Montant"].sum()
    nb_ventes = len(ventes["ID_Vente"].unique())
    top_produit = ventes.groupby("Nom_Produit")["Montant"].sum().idxmax()

    k1, k2, k3 = st.columns(3)
    k1.metric("Chiffre d'affaires total", f"{ca_total:,.0f} Ar")
    k2.metric("Nombre de factures", nb_ventes)
    k3.metric("Produit le plus rentable", top_produit)

    onglets = st.tabs([
        "📈 Courbe personnalisée", 
        "🕐 Matin vs Midi vs Après-midi", 
        "🗓️ Produits par Jour de semaine", 
        "❄️ Analyse par Saison / Fêtes",
        "🔗 Corrélation produits", 
        "⚖️ Comparer 2 produits"
    ])

    # --- 1. COURBE PERSONNALISÉE (FILTRES COMPLETS) ---
    with onglets[0]:
        st.subheader("📈 Courbe des ventes filtrable (Date, Heure, Semaine, Mois, Année)")
        
        c_f1, c_f2, c_f3 = st.columns(3)
        with c_f1:
            annees_dispo = ["Toutes"] + sorted(ventes["Annee"].unique().tolist())
            annee_sel = st.selectbox("Année", annees_dispo)
        with c_f2:
            mois_dispo = ["Tous"] + list(range(1, 13))
            mois_sel = st.selectbox("Mois", mois_dispo)
        with c_f3:
            semaines_dispo = ["Toutes"] + sorted(ventes["Semaine"].unique().tolist())
            semaine_sel = st.selectbox("Semaine de l'année", semaines_dispo)

        c_f4, c_f5 = st.columns(2)
        with c_f4:
            heure_min, heure_max = st.slider("Plage horaire (Heures)", 0, 23, (0, 23))
        with c_f5:
            prods_dispo = ["Tous"] + sorted(ventes["Nom_Produit"].unique().tolist())
            prod_sel = st.selectbox("Produit spécifique", prods_dispo)

        # Application des filtres
        df_courbe = ventes.copy()
        if annee_sel != "Toutes":
            df_courbe = df_courbe[df_courbe["Annee"] == annee_sel]
        if mois_sel != "Tous":
            df_courbe = df_courbe[df_courbe["Mois"] == mois_sel]
        if semaine_sel != "Toutes":
            df_courbe = df_courbe[df_courbe["Semaine"] == semaine_sel]
        
        df_courbe = df_courbe[(df_courbe["Heure"] >= heure_min) & (df_courbe["Heure"] <= heure_max)]

        if prod_sel != "Tous":
            df_courbe = df_courbe[df_courbe["Nom_Produit"] == prod_sel]

        if not df_courbe.empty:
            courbe_data = df_courbe.groupby("Date")["Montant"].sum().reset_index()
            fig = px.line(courbe_data, x="Date", y="Montant", markers=True, title="Évolution du CA selon vos filtres")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Aucune donnée trouvée pour cette combinaison de filtres.")

    # --- 2. MATIN vs MIDI vs APRÈS-MIDI ---
    with onglets[1]:
        st.subheader("🕐 Quel produit se vend le mieux le Matin, le Midi ou l'Après-midi ?")
        
        moment_sel = st.radio(
            "Choisir le moment de la journée :", 
            ["Matin (Avant 12h)", "Midi (12h - 14h)", "Après-midi (Après 14h)"], 
            horizontal=True
        )

        df_moment = ventes[ventes["Moment_Journee"] == moment_sel]
        
        if not df_moment.empty:
            top_moment = df_moment.groupby("Nom_Produit")[["Quantite", "Montant"]].sum().reset_index()
            top_moment = top_moment.sort_values(by="Quantite", ascending=False)
            
            fig_moment = px.bar(
                top_moment, 
                x="Nom_Produit", 
                y="Quantite", 
                color="Montant",
                title=f"Produits les plus vendus - {moment_sel}",
                labels={"Quantite": "Quantité vendue", "Nom_Produit": "Produit"}
            )
            st.plotly_chart(fig_moment, use_container_width=True)
            st.dataframe(top_moment, use_container_width=True)
        else:
            st.info(f"Aucune vente enregistrée durant la tranche : {moment_sel}")

    # --- 3. PRODUITS PAR JOUR DE LA SEMAINE ---
    with onglets[2]:
        st.subheader("🗓️ Produits vendus selon le jour de la semaine")
        
        jours_fr = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        ventes["Jour_Nom"] = ventes["DateHeure"].dt.weekday.map(lambda x: jours_fr[x])

        jour_choisi = st.selectbox("Sélectionner un jour :", jours_fr)

        df_jour = ventes[ventes["Jour_Nom"] == jour_choisi]

        if not df_jour.empty:
            st.markdown(f"### Liste des produits vendus le **{jour_choisi}**")
            
            res_jour = df_jour.groupby("Nom_Produit").agg(
                Quantite_Totale=("Quantite", "sum"),
                Montant_Total=("Montant", "sum"),
                Nombre_Ventes=("ID_Vente", "nunique")
            ).reset_index().sort_values(by="Quantite_Totale", ascending=False)

            fig_j = px.bar(
                res_jour, 
                x="Nom_Produit", 
                y="Quantite_Totale", 
                title=f"Quantités vendues le {jour_choisi}",
                text_auto=True
            )
            st.plotly_chart(fig_j, use_container_width=True)
            st.dataframe(res_jour, use_container_width=True)
        else:
            st.info(f"Aucune vente effectuée un {jour_choisi}.")

    # --- 4. ANALYSE PAR SAISON / FÊTES ---
    with onglets[3]:
        st.subheader("❄️ Ventes par Saison et périodes de Fêtes dans l'année")
        
        saison_sel = st.selectbox("Sélectionner la saison ou période :", sorted(ventes["Saison"].unique()))

        df_saison = ventes[ventes["Saison"] == saison_sel]

        if not df_saison.empty:
            st.markdown(f"### Performance des produits pendant : **{saison_sel}**")
            top_saison = df_saison.groupby("Nom_Produit")[["Quantite", "Montant"]].sum().reset_index().sort_values(by="Montant", ascending=False)
            
            fig_s = px.bar(
                top_saison, 
                x="Nom_Produit", 
                y="Montant", 
                color="Quantite",
                title=f"Chiffre d'affaires par produit - {saison_sel}"
            )
            st.plotly_chart(fig_s, use_container_width=True)
            st.dataframe(top_saison, use_container_width=True)
        else:
            st.info("Aucune donnée enregistrée pour cette saison.")

   # --- 5. CORRÉLATION GÉNÉRALE ET CIBLÉE ---
    with onglets[4]:
        st.subheader("🔗 Corrélation des ventes de produits")

        # Filtres de dates en tête de page
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            d_start = st.date_input("Date de début", ventes["DateHeure"].min().date(), key="corr_start")
        with col_d2:
            d_end = st.date_input("Date de fin", ventes["DateHeure"].max().date(), key="corr_end")

        ventes_corr = ventes[(ventes["DateHeure"].dt.date >= d_start) & (ventes["DateHeure"].dt.date <= d_end)]

        if not ventes_corr.empty:
            # Pivotement global de TOUS les produits vendus
            pivot_global = ventes_corr.pivot_table(
                index=ventes_corr["DateHeure"].dt.date, 
                columns="Nom_Produit", 
                values="Quantite", 
                aggfunc="sum"
            ).fillna(0)

            # --------------------------------------------------------
            # 1. TABLEAU GLOBAL DE CORRÉLATION (TOUS LES PRODUITS)
            # --------------------------------------------------------
            st.markdown("### 📊 Tableau de corrélation (Tous les produits vendus)")
            if pivot_global.shape[1] >= 2 and pivot_global.shape[0] > 1:
                corr_globale = pivot_global.corr()

                # Affichage sous forme de tableau numérique
                st.dataframe(
                    corr_globale.style.background_gradient(cmap="coolwarm", axis=None).format("{:.2f}"),
                    use_container_width=True
                )

                # Visualisation graphique globale (Heatmap)
                fig_global = px.imshow(
                    corr_globale, 
                    text_auto=".2f", 
                    color_continuous_scale="RdBu_r", 
                    title="Carte thermique de corrélation globale"
                )
                st.plotly_chart(fig_global, use_container_width=True)
            else:
                st.info("II faut au moins 2 produits différents et plusieurs jours de vente pour afficher le tableau global.")

            st.divider()

            # --------------------------------------------------------
            # 2. SELECTION UTILISATEUR & ANALYSE ABSCISSE (X) / ORDONNÉE (Y)
            # --------------------------------------------------------
            st.markdown("### 🎯 Analyse personnalisée (Sélection Utilisateur)")

            tous_prods = sorted(ventes_corr["Nom_Produit"].unique().tolist())
            prods_selectionnes = st.multiselect(
                "Sélectionner les produits spécifiques à analyser :",
                options=tous_prods,
                default=tous_prods[:min(5, len(tous_prods))]
            )

            if len(prods_selectionnes) >= 2:
                pivot_filtre = pivot_global[prods_selectionnes]
                corr_filtree = pivot_filtre.corr()

                st.markdown("#### Matrice des produits sélectionnés")
                st.dataframe(corr_filtree.style.format("{:.2f}"), use_container_width=True)

                st.markdown("#### Graphique Croisé : Abscisse (X) vs Ordonnée (Y)")
                cx, cy = st.columns(2)
                with cx:
                    prod_x = st.selectbox("Produit en Abscisse (X)", prods_selectionnes, index=0)
                with cy:
                    prod_y = st.selectbox("Produit en Ordonnée (Y)", prods_selectionnes, index=min(1, len(prods_selectionnes)-1))

                if prod_x in pivot_filtre.columns and prod_y in pivot_filtre.columns:
                    fig_scatter = px.scatter(
                        pivot_filtre, 
                        x=prod_x, 
                        y=prod_y,
                        trendline="ols",
                        title=f"Nuage de points : {prod_x} (X) vs {prod_y} (Y)",
                        labels={prod_x: f"Quantité de {prod_x}", prod_y: f"Quantité de {prod_y}"}
                    )
                    st.plotly_chart(fig_scatter, use_container_width=True)
            else:
                st.info("Sélectionnez au moins 2 produits ci-dessus pour afficher l'analyse croisée X/Y.")
        else:
            st.warning("Aucune vente enregistrée sur la période sélectionnée.")