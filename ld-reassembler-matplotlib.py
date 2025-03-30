import os
import subprocess
import networkx as nx
import matplotlib.pyplot as plt

# 📌 Dossier où chercher les bibliothèques
LIBRARY_DIR = "."  # Change selon tes besoins

# 📌 Fonction pour chercher tous les .so dans le dossier et sous-dossiers
def find_shared_libraries(directory):
    so_files = {}
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".so"):
                full_path = os.path.join(root, file)
                so_files[file] = full_path  # Associer nom de fichier et chemin complet
    return so_files

# 📌 Fonction pour extraire les dépendances
def get_dependencies(so_file):
    try:
        result = subprocess.run(["readelf", "-d", so_file],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deps = []
        for line in result.stdout.split("\n"):
            if "(NEEDED)" in line:
                lib = line.split("[")[-1].split("]")[0]
                deps.append(lib)
        return deps
    except Exception as e:
        print(f"Erreur lecture dépendances {so_file}: {e}")
        return []

# 📌 Fonction pour extraire les symboles (fonctions et objets)
def get_symbols(so_file):
    try:
        result = subprocess.run(["nm", "-D", so_file],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        symbols = []
        for line in result.stdout.split("\n"):
            parts = line.split()
            if len(parts) > 2 and parts[1] in ("T", "U"):  # T = fonction définie, U = utilisée
                symbols.append(parts[2])
        return symbols
    except Exception as e:
        print(f"Erreur extraction symboles {so_file}: {e}")
        return []

# 📌 Construire un graphe des dépendances
def build_dependency_graph(library_dir):
    G = nx.DiGraph()
    so_files = find_shared_libraries(library_dir)

    for so_file, full_path in so_files.items():
        G.add_node(so_file)  # Ajouter le fichier .so au graphe
        deps = get_dependencies(full_path)

        for dep in deps:
            if dep in so_files:  # Ajouter seulement si la dépendance est trouvée
                G.add_edge(so_file, dep)

    return G, so_files

# 📌 Afficher le graphe des dépendances
def plot_graph(G):
    plt.figure(figsize=(12, 8))
    pos = nx.spring_layout(G, seed=42)
    nx.draw(G, pos, with_labels=True, node_color="lightblue", edge_color="gray",
            node_size=2500, font_size=10, font_weight="bold")
    plt.title("Graphique des dépendances des bibliothèques partagées")
    plt.show()

# 📌 Exécution principale
if __name__ == "__main__":
    graph, so_files = build_dependency_graph(LIBRARY_DIR)
    plot_graph(graph)

    # 📌 Extraction et affichage des symboles pour chaque bibliothèque
    for so_file, full_path in so_files.items():
        print(f"\n🔍 Fonctions dans {so_file}:")
        symbols = get_symbols(full_path)
        for sym in symbols[:10]:  # Afficher seulement les 10 premières
            print(f"  - {sym}")
