import sys
import subprocess
import json
import re
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, 
    QFileDialog, QLabel, QWidget, QProgressBar, QTableWidget, QTableWidgetItem, QLineEdit
)
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QTextCursor


class PartitionFetcher(QThread):
    log_message = pyqtSignal(str)
    partitions_fetched = pyqtSignal(list)

    def run(self):
        self.log_message.emit("Récupération des partitions montées...")
        try:
            command = "adb shell cat /proc/mounts"
            result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                partitions = result.stdout.strip().split("\n")
                parsed_partitions = [line.split() for line in partitions]
                self.partitions_fetched.emit(parsed_partitions)
            else:
                self.log_message.emit(f"Erreur : {result.stderr}")
        except Exception as e:
            self.log_message.emit(f"Erreur pendant la récupération des partitions : {e}")


class ADBCommandExecutor(QThread):
    progress = pyqtSignal(int)
    log_message = pyqtSignal(str)
    partial_results = pyqtSignal(str, str, str)
    finished = pyqtSignal(dict)

    def __init__(self, terms, directories):
        super().__init__()
        self.terms = terms
        self.directories = directories
        self.results = {}

    def run(self):
        total_tasks = len(self.terms) * len(self.directories)
        completed_tasks = 0

        self.log_message.emit("Connexion à ADB en mode root...")
        root_result = subprocess.run(["adb", "root"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if "adbd is already running as root" not in root_result.stdout:
            self.log_message.emit("Erreur : Impossible de passer en mode root via ADB.")
            return

        for directory in self.directories:
            self.results[directory] = {}
            for term in self.terms:
                try:
                    self.log_message.emit(f"Recherche de '{term}' dans {directory}...")
                    command = f"adb shell 'grep -ri \"{term}\" {directory}'"
                    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                    while True:
                        line = process.stdout.readline()
                        if not line:
                            break

                        try:
                            # Forcer encodage en UTF-8 et ignorer les erreurs
                            clean_line = line.decode("utf-8", errors="ignore").strip()
                        except UnicodeDecodeError:
                            clean_line = f"Erreur d'encodage lors de la lecture"

                        if clean_line:  # Vérifier si la ligne est bien propre
                            self.partial_results.emit(directory, term, clean_line)
                            if term not in self.results[directory]:
                                self.results[directory][term] = []
                            self.results[directory][term].append(clean_line)

                    process.wait()
                except Exception as e:
                    self.results[directory][term] = [f"Erreur pendant l'exécution : {str(e)}"]
                completed_tasks += 1
                self.progress.emit(int((completed_tasks / total_tasks) * 100))

        self.finished.emit(self.results)


    class KernelLogFetcher(QThread):
        log_message = pyqtSignal(str)

        def run(self):
            self.log_message.emit("Démarrage de la capture des logs kernel en temps réel...")
            try:
                command = "adb shell dmesg -w"
                process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                while True:
                    line = process.stdout.readline()
                    if not line:
                        break
                    self.log_message.emit(line.strip())  # Envoie la ligne à l'interface graphique
            except Exception as e:
                self.log_message.emit(f"Erreur pendant la capture des logs : {str(e)}")


class IMEIFinderApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IMEI Finder and Kernel Debugger")
        self.setGeometry(100, 100, 1600, 900)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QPushButton { padding: 10px; border-radius: 5px; color: white; background-color: #3b3b3b; }
            QPushButton:hover { background-color: #5a5a5a; }
            QTableWidget { border: 1px solid #555; background-color: #2e2e2e; color: white; }
            QTextEdit { background-color: #2e2e2e; color: #90ee90; border: 1px solid #555; font-family: monospace; }
            QLineEdit { background-color: #2e2e2e; color: white; border: 1px solid #555; }
            QLabel { color: white; font-size: 14px; }
            QProgressBar { text-align: center; color: white; background-color: #3b3b3b; border: 1px solid #555; }
        """)

        self.initUI()
        self.output_data = {}
        self.kernel_log_fetcher = None

    def initUI(self):
        main_layout = QHBoxLayout()
        left_layout = QVBoxLayout()
        right_layout = QVBoxLayout()

        self.search_label = QLabel("Termes à rechercher (séparés par des virgules) :")
        left_layout.addWidget(self.search_label)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Exemple : IMEI,getImei,NVD_IMEI")
        left_layout.addWidget(self.search_input)

        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["Répertoire", "Terme", "Résultat"])
        left_layout.addWidget(self.results_table)

        self.progress_bar = QProgressBar()
        left_layout.addWidget(self.progress_bar)

        self.search_button = QPushButton("🔍 Rechercher")
        self.search_button.clicked.connect(self.start_search)
        left_layout.addWidget(self.search_button)

        self.export_button = QPushButton("📁 Exporter les résultats")
        self.export_button.setEnabled(False)
        self.export_button.clicked.connect(self.export_to_json)
        left_layout.addWidget(self.export_button)

        self.log_output = QTextEdit()
        left_layout.addWidget(self.log_output)

        self.partition_table = QTableWidget(0, 4)
        self.partition_table.setHorizontalHeaderLabels(["Source", "Point de Montage", "Type", "Options"])
        right_layout.addWidget(self.partition_table)

        self.fetch_partitions_button = QPushButton("🗂️ Afficher les partitions montées")
        self.fetch_partitions_button.clicked.connect(self.fetch_partitions)
        right_layout.addWidget(self.fetch_partitions_button)

        self.kernel_log_label = QLabel("🖥️ Logs Kernel en Temps Réel :")
        right_layout.addWidget(self.kernel_log_label)

        self.kernel_log_output = QTextEdit()
        self.kernel_log_output.setReadOnly(True)
        right_layout.addWidget(self.kernel_log_output)

        self.start_log_button = QPushButton("🟢 Démarrer Logs Kernel")
        self.start_log_button.clicked.connect(self.start_kernel_logging)
        right_layout.addWidget(self.start_log_button)

        self.stop_log_button = QPushButton("🔴 Arrêter Logs Kernel")
        self.stop_log_button.setEnabled(False)
        self.stop_log_button.clicked.connect(self.stop_kernel_logging)
        right_layout.addWidget(self.stop_log_button)

        main_layout.addLayout(left_layout, 3)
        main_layout.addLayout(right_layout, 2)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

    def start_kernel_logging(self):
        self.kernel_log_fetcher = KernelLogFetcher()
        self.kernel_log_fetcher.log_message.connect(self.update_kernel_logs)
        self.kernel_log_fetcher.start()
        self.start_log_button.setEnabled(False)
        self.stop_log_button.setEnabled(True)

    def stop_kernel_logging(self):
        if self.kernel_log_fetcher:
            self.kernel_log_fetcher.terminate()
        self.start_log_button.setEnabled(True)
        self.stop_log_button.setEnabled(False)

    def update_kernel_logs(self, message):
        self.kernel_log_output.append(message)
        self.kernel_log_output.moveCursor(QTextCursor.End)
    
    def log(self, message):
        self.log_output.append(message)

    def fetch_partitions(self):
            self.log("Récupération des partitions montées...")
            self.partition_fetcher = PartitionFetcher()
            self.partition_fetcher.log_message.connect(self.log)
            self.partition_fetcher.partitions_fetched.connect(self.display_partitions)
            self.partition_fetcher.start()

    def display_partitions(self, partitions):
        self.partition_table.setRowCount(0)
        for partition in partitions:
            if len(partition) >= 4:
                row_position = self.partition_table.rowCount()
                self.partition_table.insertRow(row_position)
                for col, value in enumerate(partition[:4]):
                    self.partition_table.setItem(row_position, col, QTableWidgetItem(value))

    def start_search(self):
            self.results_table.setRowCount(0)
            self.output_data = {}

            search_terms = self.search_input.text().split(",")
            directories = ["/system", "system_root", "/vendor", "/efs", "/cache", "/product"]
            self.worker = ADBCommandExecutor(search_terms, directories)
            self.worker.progress.connect(self.progress_bar.setValue)
            self.worker.log_message.connect(self.log)
            self.worker.partial_results.connect(self.add_result_row)
            self.worker.finished.connect(self.finalize_results)
            self.worker.start()

    def add_result_row(self, directory, term, match):
        row_position = self.results_table.rowCount()
        self.results_table.insertRow(row_position)
        self.results_table.setItem(row_position, 0, QTableWidgetItem(directory))
        self.results_table.setItem(row_position, 1, QTableWidgetItem(term))
        self.results_table.setItem(row_position, 2, QTableWidgetItem(match))

    def finalize_results(self, results):
        self.output_data = results
        self.log("Recherche terminée.")
        self.export_button.setEnabled(True)

    def export_to_json(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "Exporter les résultats", "", "JSON Files (*.json)")
        if file_name:
            try:
                with open(file_name, "w", encoding="utf-8") as json_file:
                    json.dump(self.output_data, json_file, ensure_ascii=False, indent=4)
                self.log(f"Résultats exportés avec succès dans {file_name}")
            except Exception as e:
                self.log(f"Erreur pendant l'exportation : {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = IMEIFinderApp()
    window.show()
    sys.exit(app.exec_())
