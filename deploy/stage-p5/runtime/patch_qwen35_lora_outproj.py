#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

OLD = '''            elif ".out_proj." in name:
                # Out projection weight: reorder columns (input dimension)
                data_torch = self._reorder_v_heads(data_torch, 1, num_k_heads, num_v_per_k, head_v_dim)
'''

NEW = '''            elif ".out_proj." in name:
                # Out projection weight: reorder columns (input dimension).
                # A LoRA weight W = B @ A can preserve its low-rank factorization
                # by applying the input-column permutation only to A.
                if hasattr(data_torch, "get_lora_A_B"):
                    col_perm = self._reorder_v_heads(
                        torch.arange(num_v_heads * head_v_dim, dtype=torch.long).unsqueeze(0),
                        1, num_k_heads, num_v_per_k, head_v_dim,
                    ).squeeze(0)
                    data_torch = data_torch[:, col_perm]
                else:
                    data_torch = self._reorder_v_heads(
                        data_torch, 1, num_k_heads, num_v_per_k, head_v_dim
                    )
'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_qwen35_lora_outproj.py PATH")
    path = Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"unexpected Qwen3.5 out_proj source block count: {count}")
    if NEW in text:
        raise SystemExit("Qwen3.5 LoRA out_proj patch already present")
    path.write_text(text.replace(OLD, NEW), encoding="utf-8")
    verify = path.read_text(encoding="utf-8")
    if verify.count(NEW) != 1 or OLD in verify:
        raise SystemExit("Qwen3.5 LoRA out_proj patch verification failed")
    print("QWEN35_LORA_OUTPROJ_PATCH=PASS")


if __name__ == "__main__":
    main()
