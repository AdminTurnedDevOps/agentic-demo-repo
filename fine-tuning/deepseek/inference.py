"""
Test the fine-tuned Llama + LoRA model on Istio Ambient Mesh questions.

This script:
1. Loads the base Llama model
2. Loads the trained LoRA adapter weights
3. Generates answers to Istio Ambient Mesh questions
"""

import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
import sys

# ============================================================================
# CONFIGURATION
# ============================================================================

# BASE_MODEL = "meta-llama/Llama-2-7b-hf"  # Same base model used for training
# BASE_MODEL = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"  # Small general model
BASE_MODEL = "deepseek-ai/deepseek-coder-1.3b-base"  # Best for technical content!

LORA_WEIGHTS = "./results/final_model"   # Path to your trained LoRA adapter
MAX_NEW_TOKENS = 256                     # Maximum tokens to generate
TEMPERATURE = 0.7                        # Sampling temperature (0.0 = greedy, 1.0 = random)
TOP_P = 0.9                              # Nucleus sampling threshold

# ============================================================================
# MODEL LOADING
# ============================================================================

def load_model():
    """
    Load the base model and merge it with the LoRA adapter.

    Returns:
        model: The model with LoRA weights applied
        tokenizer: The tokenizer
    """
    print("Loading base model and tokenizer...")

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.pad_token = tokenizer.eos_token

    # Load base model - no quantization on Mac (bitsandbytes requires CUDA)
    print("Loading base model (this may take a minute)...")
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        device_map="auto",
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )

    # Load LoRA adapter weights
    print(f"Loading LoRA adapter from {LORA_WEIGHTS}...")
    model = PeftModel.from_pretrained(base_model, LORA_WEIGHTS)

    print("Model loaded successfully!\n")
    return model, tokenizer

# ============================================================================
# INFERENCE
# ============================================================================

def generate_answer(question, model, tokenizer):
    """
    Generate an answer to a question using the fine-tuned model.

    Args:
        question: The question to ask
        model: The model with LoRA adapter
        tokenizer: The tokenizer

    Returns:
        The generated answer
    """
    # Format the question in the same format used during training
    prompt = f"### Question: {question}\n### Answer:"

    # Tokenize the input
    inputs = tokenizer(prompt, return_tensors="pt")

    # Move to the same device as model
    inputs = {k: v.to(model.device) for k, v in inputs.items()}

    # Generate response
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            top_p=TOP_P,
            do_sample=True,              # Use sampling instead of greedy decoding
            pad_token_id=tokenizer.eos_token_id,
        )

    # Decode the generated tokens
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # Extract just the answer part (after "### Answer:")
    if "### Answer:" in generated_text:
        answer = generated_text.split("### Answer:")[1].strip()
    else:
        answer = generated_text

    return answer

# ============================================================================
# INTERACTIVE MODE
# ============================================================================

def interactive_mode(model, tokenizer):
    """
    Run an interactive Q&A session.
    """
    print("="*60)
    print("Istio Ambient Mesh Troubleshooting Assistant")
    print("(Powered by Llama + LoRA)")
    print("="*60)
    print("\nType your questions about Istio Ambient Mesh.")
    print("Type 'quit' or 'exit' to stop.\n")

    while True:
        # Get question from user
        question = input("\nQuestion: ").strip()

        if question.lower() in ['quit', 'exit', 'q']:
            print("Goodbye!")
            break

        if not question:
            continue

        # Generate answer
        print("\nGenerating answer...")
        answer = generate_answer(question, model, tokenizer)

        print("\n" + "-"*60)
        print(f"Answer:\n{answer}")
        print("-"*60)

# ============================================================================
# DEMO MODE
# ============================================================================

def demo_mode(model, tokenizer):
    """
    Run a few demo questions to showcase the model.
    """
    demo_questions = [
        "How do I check if Istio Ambient Mesh is properly installed?",
        "What's the difference between ztunnel and waypoint proxy?",
        "My pods are not being enrolled in the ambient mesh. What should I check?",
    ]

    print("="*60)
    print("Running demo with sample questions...")
    print("="*60)

    for i, question in enumerate(demo_questions, 1):
        print(f"\n{'='*60}")
        print(f"Demo Question {i}/{len(demo_questions)}:")
        print(f"{question}")
        print("-"*60)

        answer = generate_answer(question, model, tokenizer)

        print(f"Answer:\n{answer}")
        print("="*60)

    print("\nDemo complete!")

# ============================================================================
# MAIN
# ============================================================================

def main():
    """
    Main function - supports demo mode and interactive mode.
    """
    # Load model
    model, tokenizer = load_model()

    # Check command line arguments
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        # Run demo mode
        demo_mode(model, tokenizer)
    elif len(sys.argv) > 1 and sys.argv[1] == "--question":
        # Answer a single question from command line
        question = " ".join(sys.argv[2:])
        answer = generate_answer(question, model, tokenizer)
        print(f"\nQuestion: {question}")
        print(f"\nAnswer:\n{answer}\n")
    else:
        # Run interactive mode
        interactive_mode(model, tokenizer)

if __name__ == "__main__":
    main()
