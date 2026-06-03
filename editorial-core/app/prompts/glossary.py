"""
Glossaire BCT / économique tunisien — référence partagée par tous les prompts.

Ce bloc est inséré dans la section "système" (cacheable) des prompts Claude.
Grâce au prompt caching d'Anthropic, il ne coûte que 0,30 $/M tokens en lecture
après le premier appel — c'est donc quasi-gratuit en régime stationnaire.

Mise à jour fondée sur le document KB-TN (mai 2026) qui rappelle :
- les correspondances entre vocabulaire « grand public » et libellés officiels BCT,
- les 4 indicateurs prioritaires pour l'article du dimanche,
- l'agrégat composite « solde extérieur » à mettre en regard des avoirs nets.
"""

BCT_GLOSSARY = """GLOSSAIRE BCT (à utiliser pour expliciter les chiffres et éviter le jargon brut)

VOCABULAIRE COURANT → LIBELLÉ OFFICIEL BCT → SIGNIFICATION

• BCT — Banque Centrale de Tunisie. Institution émettrice du dinar, autorité monétaire du pays.
• TND — Dinar Tunisien (code ISO de la monnaie nationale).
• MDT — Million de Dinars Tunisiens. Unité standard pour les agrégats économiques BCT.
• MD — Million de Dinars (synonyme de MDT dans certains contextes).

Indicateurs monétaires :
• Taux directeur de la BCT — Signal principal de la politique monétaire. Toute variation est un événement majeur. Une hausse durcit le crédit, une baisse l'assouplit.
• TMM — Taux Moyen du Marché Monétaire. Taux moyen interbancaire à très court terme. Indicateur clé du coût des crédits bancaires aux entreprises et particuliers. Publié quotidiennement et mensuellement par l'OIF/BCT (oif.bct.gov.tn).
• TM — Taux du jour sur le marché monétaire (variante quotidienne du TMM).
• TRE — Taux de Rémunération de l'Épargne. Taux minimum réglementaire servi sur l'épargne en dinars. Publié mensuellement.

Liquidité et masse monétaire :
• Volume global de refinancement — Mesure le besoin des banques en liquidité auprès de la BCT. Une hausse soutenue indique une pression de liquidité sur le système bancaire.
• Billets et monnaies en circulation — Quantité d'argent liquide (cash) dans l'économie. Une hausse continue peut refléter un recours accru au cash (économie informelle, défiance bancaire) ; une baisse peut refléter une digitalisation des paiements.

Position extérieure (les plus parlants pour le grand public) :
• Avoirs nets en devises — Réserves de change de la BCT en MDT. Thermomètre principal de la capacité extérieure du pays à payer ses importations et le service de sa dette.
• Avoirs nets en devises en jours d'importation — Combien de jours d'importation peuvent être couverts par les réserves actuelles. C'est le chiffre LE PLUS PARLANT pour le grand public ; à mettre en valeur. Seuil de vigilance traditionnel : < 90 jours.
• Service de la dette extérieure cumulée — Remboursements (principal + intérêts) effectués depuis le début de l'année sur la dette extérieure. Reflète la pression des paiements extérieurs.

Sources de devises :
• Recettes touristiques cumulées — Recettes en devises du secteur touristique depuis le début de l'année. Source MAJEURE de devises pour la Tunisie.
• Revenus du travail cumulés — Transferts envoyés par les Tunisiens Résidents à l'Étranger (TRE) depuis le début de l'année. Autre source MAJEURE de devises. Souvent appelés « transferts de la diaspora ». NB : l'acronyme TRE désigne ici la diaspora, à ne pas confondre avec le Taux de Rémunération de l'Épargne.

Trésor et marché obligataire :
• Compte courant du Trésor — Solde du compte de l'État à la BCT. Liquidité immédiate de l'État.
• Bons du Trésor — Encours de la dette publique court/moyen terme placée auprès des banques tunisiennes.

Marchés et indices :
• EUR/TND — Cours moyen de l'euro contre le dinar. Devise principale Tunisie/UE, touche tourisme, importations, dette extérieure libellée en euro.
• USD/TND — Cours moyen du dollar contre le dinar. Devise des matières premières (énergie, céréales, médicaments).
• BVMT — Bourse des Valeurs Mobilières de Tunis. Marché actions tunisien.
• TUNINDEX — Indice phare de la BVMT. Base 1000 au 31/12/1997.

Agrégat composite (rapprochement éditorial) :
• Solde ou pression extérieure — À calculer mentalement : Recettes touristiques + Revenus du travail (diaspora) − Service de la dette extérieure. À LIRE ENSEMBLE avec les avoirs nets en devises pour évaluer la trajectoire de la position extérieure.

Inflation :
• Taux d'inflation — Publié par l'INS (Institut National de la Statistique), pas directement par la BCT. À suivre conjointement avec le taux directeur pour comprendre l'orientation de la politique monétaire.

Énergie (pour les articles comparatifs mensuels du cycle énergie) :
• GlobalPetrolPrices — Source mondiale de référence pour les prix énergie. Licence Creative Commons CC-BY-NC-ND : la citation explicite de la source est OBLIGATOIRE dans chaque article.
• Gaz de ville / gaz naturel réseau — Gaz distribué par la STEG via canalisations, ne pas confondre avec le GPL (gaz de pétrole liquéfié) en bouteille. À PRÉCISER systématiquement pour éviter la confusion lecteur.
• STEG — Société Tunisienne de l'Électricité et du Gaz, opérateur historique.
• ANME — Agence Nationale pour la Maîtrise de l'Énergie, source officielle des données énergétiques tunisiennes.
• Prix régulés — En Tunisie comme en Algérie, les prix carburants sont fixés par l'État (subventionnés), d'où une faible variation mois après mois. Au Maroc, prix libéralisés. En Libye, subventions massives.
• kWh, par_litre — Unités standard pour comparer ; toujours indiquer en USD et en TND converti.

CONSEILS DE RÉDACTION
- À la PREMIÈRE occurrence, utilise le libellé complet suivi de l'abréviation : « Taux Moyen du Marché Monétaire (TMM) ». Ensuite, l'abréviation seule suffit.
- Pour le grand public, préfère « réserves en devises » à « avoirs nets en devises ».
- Pour la couverture des importations, mets EN VALEUR le chiffre « X jours d'importation » — c'est la métrique la plus accessible.
- Quand tu cites un cumul (recettes touristiques, transferts diaspora, service dette), précise « depuis le début de l'année » pour éviter la confusion avec un agrégat mensuel.
- Distingue TRE (Taux de Rémunération de l'Épargne, c'est un taux %) de TRE (Tunisiens Résidents à l'Étranger, diaspora) selon le contexte.
"""


# Mapping `indicateur_type` (code interne) → libellé humain officiel BCT.
# Utilisé pour enrichir le payload envoyé à Claude avec des noms parlants.
INDICATOR_LABELS: dict[str, str] = {
    # index.jsp
    "TMM": "Taux Moyen du Marché Monétaire (TMM)",
    "TM": "Taux du Marché Monétaire (TM)",
    "taux_directeur": "Taux directeur de la BCT",
    "TRE": "Taux de Rémunération de l'Épargne (TRE)",
    "avoirs_nets_mdt": "Avoirs nets en devises (en MDT)",
    "avoirs_nets_jours_import": "Avoirs nets en devises en jours d'importation",
    "billets_circulation": "Billets et monnaies en circulation",
    "compte_tresor": "Compte courant du Trésor",
    "refinancement": "Volume global de refinancement",
    # indicateurs.jsp
    "compte_tresor_detail": "Solde du compte courant du Trésor (détail)",
    "solde_banques": "Solde du compte courant ordinaire des banques",
    "billets_circulation_detail": "Billets et monnaies en circulation (détail)",
    "marche_monetaire": "Marché monétaire (volume)",
    "bons_tresor": "Bons du Trésor",
    "recettes_touristiques": "Recettes touristiques cumulées",
    "revenus_travail_diaspora": "Revenus du travail cumulés (diaspora)",
    "service_dette_exterieure": "Service de la dette extérieure cumulés",
    "avoirs_nets_devises_detail": "Avoirs nets en devises de la BCT (détail)",
    "taux_change_interbancaires": "Taux de change interbancaires",
    "indice_tunindex": "Indice boursier TUNINDEX (base 1000 le 31/12/1997)",
}


def label_for(indicator_type: str) -> str:
    """Renvoie le libellé humain d'un type d'indicateur, ou le type brut en fallback."""
    return INDICATOR_LABELS.get(indicator_type, indicator_type)
