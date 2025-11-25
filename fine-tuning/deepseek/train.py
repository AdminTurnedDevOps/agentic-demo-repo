"""
Fine-tune Llama model with LoRA on Istio Ambient Mesh troubleshooting data.

This script demonstrates:
1. Loading a pre-trained Llama model
2. Applying LoRA (Low-Rank Adaptation) for efficient fine-tuning
3. Training on custom Istio Ambient Mesh dataset
4. Saving the trained adapter weights
"""

import json
import torch
from datasets import Dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
import os

# ============================================================================
# CONFIG
# ============================================================================

# Model configuration
# MODEL_NAME = "meta-llama/Llama-2-7b-hf"  # You'll need HuggingFace access to Llama
# MODEL_NAME = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"  # Small general model
MODEL_NAME = "deepseek-ai/deepseek-coder-1.3b-base"  # Best for technical content!

# LoRA configuration - These parameters control the adapter layer
LORA_R = 16                    # Rank of the adapter matrices (higher = more capacity, more params)
LORA_ALPHA = 32                # Scaling factor (typically 2x the rank)
LORA_DROPOUT = 0.05            # Dropout for regularization
LORA_TARGET_MODULES = [        # Which layers to add adapters to
    "q_proj",                  # Query projection in attention
    "k_proj",                  # Key projection in attention
    "v_proj",                  # Value projection in attention
    "o_proj",                  # Output projection in attention
]

# Training configuration
OUTPUT_DIR = "./results"
DATASET_PATH = "./istio_ambient_dataset.json"
MAX_LENGTH = 512               # Maximum sequence length
BATCH_SIZE = 4                 # Batch size per device (M3 Max can handle 4-8)
GRADIENT_ACCUMULATION = 4      # Accumulate gradients over N steps (effective batch = 4*4=16)
LEARNING_RATE = 2e-4           # Learning rate for AdamW optimizer
NUM_EPOCHS = 3                 # Number of training epochs
WARMUP_STEPS = 50              # Learning rate warmup steps
SAVE_STEPS = 100               # Save checkpoint every N steps
LOGGING_STEPS = 10             # Log metrics every N steps

# ============================================================================
# DATASET PREPARATION
# ============================================================================

def load_and_format_dataset(dataset_path):
    """
    Load the Istio Ambient Mesh dataset and format it for instruction tuning.

    The dataset format is:
    {
        "instruction": "Question about Istio",
        "input": "Optional context",
        "output": "Answer to the question"
    }

    We'll format this as: <instruction>\n\n<output>
    """
    print(f"Loading dataset from {dataset_path}...")

    with open(dataset_path, 'r') as f:
        data = json.load(f)

    # Format each example as a prompt-completion pair
    formatted_data = []
    for item in data:
        # Create instruction format
        if item['input']:
            text = f"### Question: {item['instruction']}\n### Context: {item['input']}\n### Answer: {item['output']}"
        else:
            text = f"### Question: {item['instruction']}\n### Answer: {item['output']}"

        formatted_data.append({"text": text})

    print(f"Loaded {len(formatted_data)} examples")

    # Convert to HuggingFace Dataset
    dataset = Dataset.from_list(formatted_data)
    return dataset

def tokenize_function(examples, tokenizer):
    """
    Tokenize the text examples.

    This converts text into token IDs that the model can process.
    """
    return tokenizer(
        examples["text"],
        truncation=True,
        max_length=MAX_LENGTH,
        padding="max_length"
    )

# ============================================================================
# MODEL SETUP
# ============================================================================

def setup_model_and_tokenizer(model_name):
    """
    Load the base model and tokenizer, then apply LoRA.

    Steps:
    1. Load tokenizer
    2. Load model (full precision on Mac, no quantization)
    3. Apply LoRA configuration
    """
    print(f"Loading model: {model_name}")

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.pad_token = tokenizer.eos_token  # Set padding token
    tokenizer.padding_side = "right"           # Pad on the right side

    # Load model - no quantization on Mac (bitsandbytes requires CUDA)
    # M3 Max has unified memory, so we can load the full model
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        device_map="auto",                  # Automatically use available device (MPS/CPU)
        torch_dtype=torch.bfloat16,        # Use bfloat16 (works well on Apple Silicon)
        low_cpu_mem_usage=True,            # Optimize memory loading
    )

    # Configure LoRA
    # This creates the small adapter matrices that will be trained
    lora_config = LoraConfig(
        r=LORA_R,                           # Rank of adapter matrices
        lora_alpha=LORA_ALPHA,              # Scaling factor
        target_modules=LORA_TARGET_MODULES, # Which layers to adapt
        lora_dropout=LORA_DROPOUT,          # Dropout rate
        bias="none",                        # Don't train bias terms
        task_type="CAUSAL_LM"               # Causal language modeling task
    )

    # Apply LoRA to the model
    # This freezes the base model and adds trainable adapter layers
    model = get_peft_model(model, lora_config)

    # Print trainable parameters
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"\n{'='*60}")
    print(f"Trainable params: {trainable_params:,} ({100 * trainable_params / total_params:.2f}%)")
    print(f"Total params: {total_params:,}")
    print(f"LoRA is saving you from training {total_params - trainable_params:,} parameters!")
    print(f"{'='*60}\n")

    return model, tokenizer

# ============================================================================
# TRAINING
# ============================================================================

def train():
    """
    Main training function.
    """
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load dataset
    dataset = load_and_format_dataset(DATASET_PATH)

    # Setup model and tokenizer
    model, tokenizer = setup_model_and_tokenizer(MODEL_NAME)

    # Tokenize dataset
    print("Tokenizing dataset...")
    tokenized_dataset = dataset.map(
        lambda x: tokenize_function(x, tokenizer),
        batched=True,
        remove_columns=dataset.column_names
    )

    # Data collator for language modeling
    # This handles batching and creates labels from inputs
    data_collator = DataCollatorForLanguageModeling(
        tokenizer=tokenizer,
        mlm=False  # We're doing causal LM, not masked LM
    )

    # Training arguments
    # These control how the training loop behaves
    training_args = TrainingArguments(
        output_dir=OUTPUT_DIR,
        num_train_epochs=NUM_EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRADIENT_ACCUMULATION,
        learning_rate=LEARNING_RATE,
        warmup_steps=WARMUP_STEPS,
        logging_steps=LOGGING_STEPS,
        save_steps=SAVE_STEPS,
        save_total_limit=3,              # Keep only 3 checkpoints
        fp16=False,                      # M3 Max doesn't support fp16 well
        bf16=True,                       # Use bfloat16 instead (better for Apple Silicon)
        optim="adamw_torch",             # Optimizer
        logging_dir=f"{OUTPUT_DIR}/logs",
        report_to="none",                # Don't report to wandb/tensorboard
        push_to_hub=False,               # Don't push to HuggingFace Hub
    )

    # Create Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized_dataset,
        data_collator=data_collator,
    )

    print("\n" + "="*60)
    print("Starting training...")
    print("="*60 + "\n")

    trainer.train()

    # Save the final LoRA adapter weights
    # These are the only weights that changed during training
    final_model_path = f"{OUTPUT_DIR}/final_model"
    model.save_pretrained(final_model_path)
    tokenizer.save_pretrained(final_model_path)

    print("\n" + "="*60)
    print(f"Training complete! LoRA adapter saved to: {final_model_path}")
    print(f"Adapter size: ~20-50MB (vs ~14GB for full model)")
    print("="*60 + "\n")
    

if __name__ == "__main__":
    # Check for MPS (Metal Performance Shaders) on Mac
    if torch.backends.mps.is_available():
        print("MPS (Apple Silicon GPU) is available!")
    else:
        print("MPS not available, using CPU (will be slower)")

    train()
