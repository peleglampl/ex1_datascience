import pandas as pd
import numpy as np
import visualisation as viz

# Do not modify this class, there is no error inside !
class HujinatorNode:
    """Core data structure for the Decision Tree."""

    def __init__(self, feature=None, results=None, children=None):
        self.feature = feature
        self.results = results
        self.children = children or {}


def calculate_entropy(target_col):
    """Calculates the Shannon Entropy of a target column."""
    probabilities = target_col.value_counts(normalize=True)
    return -sum(p * np.log2(p) for p in probabilities if p > 0)

def calculate_information_gain(data, feature, target_name):
    """Calculates the Information Gain (IG) for a specific feature."""
    total_entropy = calculate_entropy(data[target_name])

    values = data[feature].unique()
    weighted_entropy = 0
    for val in values:
        subset = data[data[feature] == val]
        weight = len(subset) / len(data)
        weighted_entropy += weight * calculate_entropy(subset[target_name])

    return total_entropy - weighted_entropy

def build_tree(data, features, target_name='Beloved', depth=0, max_depth=5, min_samples_split=10):
    """
    Recursive ID3 construction with added pruning parameters to avoid messy, deep trees.
    """
    target_values = data[target_name].unique()

    if len(target_values) == 1:
        return HujinatorNode(results=target_values[0])

    if not features:
        return HujinatorNode(results=data[target_name].value_counts().idxmax())

    # Calculate Gain for each feature
    gains = {f: calculate_information_gain(data, f, target_name) for f in features}

    best_feature = max(sorted(gains.keys()), key=lambda f: gains[f])

    if gains[best_feature] <= 0:
        return HujinatorNode(results=data[target_name].value_counts().idxmax())

    # Create the decision node
    node = HujinatorNode(feature=best_feature)

    remaining_features = [f for f in features if f != best_feature]

    # Create children for each possible value of the best feature
    for val in data[best_feature].unique():
        subset = data[
            data[best_feature] == val]

        # if subset.empty:
        if subset.size < min_samples_split:
            continue
        else:
            # Recurse: build the next level
            node.children[val] = build_tree(subset, remaining_features, target_name,
                                            depth + 1, max_depth, min_samples_split)

    return node


# --- MAIN EXECUTION ---
if __name__ == "__main__":
    try:
        # Load Data
        df = pd.read_csv('hujinator_1000.csv')

        potential_features = [col for col in df.columns if col not in ['Beloved', 'Student_ID']]

        # Train Model with pruning parameters
        root = build_tree(df, potential_features)

        # Visual Summary in Console
        viz.print_tree_summary(root)

        viz.generate_tree_image(root, filename='hujinator_tree.png')

    except FileNotFoundError:
        print("Error: 'hujinator_1000.csv' not found.")