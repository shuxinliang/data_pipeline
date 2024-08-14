#!/usr/bin/env python
# coding: utf-8

# import packages
import lamindb as ln
import anndata as ad
import bionty as bt
import scanpy as sc
import pandas as pd
from fuzzywuzzy import fuzz
from fuzzywuzzy import process
import subprocess
from GPT import *

class DataProcessor:
    def __init__(self, adata_path,source_id):
        self.adata = sc.read_h5ad(adata_path)
        self.obs_df = self.adata.obs.copy()
        self.description = source_id
    
    def fuzzy_match_columns(self, obs_columns, required_columns):
        matched_columns = GPT_for_column(obs_columns)
        print("Match:")
        for req_col, matched_col in matched_columns.items():
            print(f"{req_col}: {matched_col}")
            if matched_col is not None:
                self.obs_df[req_col] = self.obs_df[matched_col]
            else:
                self.obs_df[req_col] = None
        self.adata.obs = self.obs_df

    def map_ontology(self, column_name, ontology_class, original_col, mapped_col, ontology_id_col):
        bionty = ontology_class.public()
        name_mapper = {}
        ontology_id_mapper = {}

        for name in self.adata.obs[original_col].unique():
            if name is not None and isinstance(name, str) and name.strip():
                search_result = bionty.search(name)
                if not search_result.empty:
                    ontology_id = search_result.iloc[0].ontology_id
                    # print(name)   
                    record = ontology_class.from_source(ontology_id=ontology_id)
                    name_mapper[name] = record.name
                    ontology_id_mapper[name] = ontology_id
                    record.save()
                    record.add_synonym(name)
                else:
                    name_mapper[name] = "unknown"
                    ontology_id_mapper[name] = "unknown"
            else:
                name_mapper[name] = "unknown"
                ontology_id_mapper[name] = "unknown"
        
        self.adata.obs[mapped_col] = self.adata.obs[original_col].map(name_mapper)
        self.adata.obs[ontology_id_col] = self.adata.obs[original_col].map(ontology_id_mapper)
    
    def detect_species(self):
        gene_ids = self.adata.var_names.unique()
        human_count = sum(1 for gene in gene_ids if gene.startswith('ENSG'))
        mouse_count = sum(1 for gene in gene_ids if gene.startswith('ENSMUSG'))

        if human_count > mouse_count:
            return 'human'
        elif mouse_count > human_count:
            return 'mouse'
        else:
            return 'unknown'

    def process_data(self):
        required_columns = [
            "dataset_id", 
            "assay", 
            "cell_type_original", 
            "development_stage_original", 
            "disease_original",
            "tissue_original",
            "donor_id",
            "sex", 
            "is_primary"
        ]
        self.fuzzy_match_columns(self.adata.obs.columns.tolist(), required_columns)

        # Map various ontologies
        self.map_ontology("assay", bt.ExperimentalFactor, "assay", "assay_ontology", "assay_ontology_id")
        self.map_ontology("cell_type_original", bt.CellType, "cell_type_original", "cell_type_ontology", "cell_type_ontology_id")
        self.map_ontology("development_stage_original", bt.DevelopmentalStage, "development_stage_original", "development_stage_ontology", "development_stage_ontology_id")
        self.map_ontology("disease_original", bt.Disease, "disease_original", "disease_ontology", "disease_ontology_id")
        self.map_ontology("tissue_original", bt.Tissue, "tissue_original", "tissue_ontology", "tissue_ontology_id")

        # Convert all elements of the data box to string type
        self.adata.obs = self.adata.obs.applymap(str)

        # Define categorical variables and their mappings
        categoricals = {
            self.adata.obs.assay_ontology.name: bt.ExperimentalFactor.name,
            self.adata.obs.cell_type_ontology.name: bt.CellType.name,
            self.adata.obs.cell_type_ontology_id.name: bt.CellType.ontology_id,
            self.adata.obs.development_stage_ontology.name: bt.DevelopmentalStage.name,
            self.adata.obs.development_stage_ontology_id.name: bt.DevelopmentalStage.ontology_id,
            self.adata.obs.disease_ontology.name: bt.Disease.name,
            self.adata.obs.disease_ontology_id.name: bt.Disease.ontology_id,
            self.adata.obs.tissue_ontology.name: bt.Tissue.name,
            self.adata.obs.tissue_ontology_id.name: bt.Tissue.ontology_id,
        }

        # Detect species
        species = self.detect_species()

        # Create a Curate object to guide validation and annotation
        curate = ln.Curate.from_anndata(
            self.adata, 
            var_index=bt.Gene.ensembl_gene_id,
            categoricals=categoricals, 
            organism=species,
        )

        # Add new records to the database from the variable index
        curate.add_new_from_var_index()

        # Validate the data
        curate.validate()

        # Save artifact
        artifact = curate.save_artifact(description=self.description)

        return artifact

class LaminDBManager:
    def __init__(self, storage_path):
        self.storage_path = storage_path

    def initialize(self):
        subprocess.run(['lamin', 'init', '--storage', self.storage_path, '--schema', 'bionty'])
        ln.setup.settings.instance._keep_artifacts_local = True

    def close(self):
        subprocess.run(['lamin', 'close'])

    def list_artifacts(self):
        return ln.Artifact.df()

    def upload_artifact(self, artifact):
        artifact.save(upload=True)

    def view_tree(self):
        return ln.setup.settings.storage.root.view_tree()


# Main workflow
def main():
    # 创建解析器对象
    # parser = argparse.ArgumentParser(description='Process some integers.')

    # # 添加参数
    # parser.add_argument('--source_id', type=str, required=True, help='The source ID to process')

    # # 解析参数
    # args = parser.parse_args()

    # # 获取参数值
    # source_id = args.source_id

    # # 打印参数值
    # print(f'Source ID: {source_id}')
    source_id = "GSE161382"
    lamin_db_manager = LaminDBManager('s3://cartabio/ai/data/fujing_test')
    lamin_db_manager.initialize()

    processor = DataProcessor('/home/ubuntu/kchen/data_pipeline/test/dataforload/kang_processing.h5ad',source_id)
    artifact = processor.process_data()

    print(lamin_db_manager.list_artifacts())
    lamin_db_manager.upload_artifact(artifact)
    lamin_db_manager.view_tree()

    lamin_db_manager.close()

if __name__ == "__main__":
    main()