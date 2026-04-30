import matplotlib.pyplot as plt
import networkx as nx

import matplotlib.pyplot as plt
import networkx as nx


def generate_tree_image(node, filename='hujinator_tree_clean.png'):
    """
    Generates a decision tree visualization with a strict hierarchical layout.
    Uses object IDs to ensure every node is unique, even if data is redundant.
    """
    G = nx.DiGraph()
    pos = {}
    labels = {}
    edge_labels = {}

    def add_to_graph(n, x=0, y=0, layer=1, width=2.0):
        nonlocal G

        # Use unique object memory address as ID to prevent accidental node merging
        my_id = id(n)

        # Determine visual properties based on node type
        if n.results is not None:
            # Leaf node
            color = '#90ee90' if n.results == 'Yes' else '#ffcccb'
            label = f"Result: {n.results}"
        else:
            # Decision node
            color = '#add8e6'
            label = f"{n.feature}"

        # Store attributes directly in the NetworkX node
        G.add_node(my_id, color=color, label=label)
        pos[my_id] = (x, -y)  # Negative y ensures the tree grows downward
        labels[my_id] = label

        # Stop recursion if it's a leaf or has no children
        if n.results is not None or not n.children:
            return my_id

        # Calculate horizontal spacing for children
        num_children = len(n.children)
        step = width / num_children
        start_x = x - (width / 2) + (step / 2)

        for i, (val, child) in enumerate(n.children.items()):
            child_x = start_x + i * step
            child_id = add_to_graph(child, child_x, y + 1, layer + 1, width / 1.5)

            G.add_edge(my_id, child_id)
            edge_labels[(my_id, child_id)] = str(val)

        return my_id

    # 1. Build the graph structure
    add_to_graph(node, width=10.0)

    # 2. Extract colors in the EXACT order of nodes in G to avoid size mismatch
    node_colors = [G.nodes[n]['color'] for n in G.nodes()]

    # 3. Plotting
    plt.figure(figsize=(25, 15))  # Large canvas to prevent text overlap
    nx.draw(G, pos, labels=labels, with_labels=True,
            node_size=5000, node_color=node_colors, node_shape='s',
            font_size=8, font_weight='bold', edge_color='#b1b1b1',
            arrows=True, arrowsize=20)

    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, font_size=7)

    plt.title("Hujinator Decision Tree - Educational View", fontsize=20)
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Successfully saved tree visualization to: {filename}")


def print_tree_summary(node):
    """
    Prints basic tree statistics to the console.
    """

    def count_nodes(n):
        if n.results is not None:
            return 1, 1  # (total_nodes, leaf_count)
        total, leaves = 1, 0
        for child in n.children.values():
            t, l = count_nodes(child)
            total += t
            leaves += l
        return total, leaves

    total, leaves = count_nodes(node)
    print(f"\n--- Hujinator Summary ---")
    print(f"Total Nodes: {total}")
    print(f"Total Leaves: {leaves}")
    print(f"-------------------------\n")