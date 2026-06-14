"""正規表現定数を用途別に集約する。

用途が違えば形が似ていても別ファイルに置く（規約 R2）。サブモジュール:
- snippet_boundaries: スニペット切り出しの境界判定用
- literal_masking: 言語別リテラル/コメントのマスク用
- symbol_extraction: 言語別シンボル抽出用
"""
