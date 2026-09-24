import numpy as np
import logging

log = logging.getLogger(__name__)

class DawidSkeneAggregator:
    """
    A modular implementation of the Dawid-Skene algorithm (Expectation-Maximization)
    for ensembling multiple trading models (e.g., Ridge, XGB, LSTM).
    
    Instead of hardcoding weights, it dynamically learns the reliability (confusion matrix) 
    of each model based on their historical accuracy and bias.
    """
    def __init__(self, n_models=3, n_classes=2):
        self.n_models = n_models
        self.n_classes = n_classes
        
        # Initialize confusion matrices (reliability) for each model: [model, true_class, pred_class]
        # Start with identity matrix + slight noise (assume they are somewhat accurate)
        self.confusion_matrices = np.zeros((n_models, n_classes, n_classes))
        for m in range(n_models):
            self.confusion_matrices[m] = np.eye(n_classes) * 0.8 + 0.1
            
        self.class_priors = np.ones(n_classes) / n_classes

    def fit(self, predictions: np.ndarray, max_iter=20, tol=1e-4):
        """
        Estimate model reliabilities using Expectation-Maximization.
        
        predictions: np.ndarray of shape (n_samples, n_models)
                     Values should be discrete class labels (e.g., 0 for short, 1 for long).
        """
        if predictions.size == 0:
            return
            
        n_samples = predictions.shape[0]
        
        # Initialize true label estimates (Expectation step)
        # T[i, j] = probability that sample i is class j
        T = np.ones((n_samples, self.n_classes)) / self.n_classes
        
        for iteration in range(max_iter):
            # --- M-step: Update confusion matrices and priors based on T ---
            self.class_priors = np.sum(T, axis=0) / n_samples
            
            for m in range(self.n_models):
                for j in range(self.n_classes): # True class
                    for k in range(self.n_classes): # Predicted class
                        mask = (predictions[:, m] == k)
                        self.confusion_matrices[m, j, k] = np.sum(T[mask, j])
                    
                    # Normalize
                    row_sum = np.sum(self.confusion_matrices[m, j, :])
                    if row_sum > 0:
                        self.confusion_matrices[m, j, :] /= row_sum
                    else:
                        self.confusion_matrices[m, j, :] = 1.0 / self.n_classes

            # --- E-step: Update T based on new confusion matrices and priors ---
            T_new = np.zeros((n_samples, self.n_classes))
            for i in range(n_samples):
                for j in range(self.n_classes):
                    prob = self.class_priors[j]
                    for m in range(self.n_models):
                        pred_k = int(predictions[i, m])
                        prob *= self.confusion_matrices[m, j, pred_k]
                    T_new[i, j] = prob
                
                # Normalize row
                row_sum = np.sum(T_new[i, :])
                if row_sum > 0:
                    T_new[i, :] /= row_sum
                else:
                    T_new[i, :] = 1.0 / self.n_classes
                    
            # Check convergence
            diff = np.max(np.abs(T_new - T))
            T = T_new
            if diff < tol:
                log.debug(f"Dawid-Skene converged in {iteration+1} iterations.")
                break
                
        return T

    def predict_proba(self, current_predictions: np.ndarray) -> np.ndarray:
        """
        Given the current predictions of the models, return the ensemble probability.
        current_predictions: np.ndarray of shape (n_models,)
        """
        probs = np.zeros(self.n_classes)
        for j in range(self.n_classes):
            prob = self.class_priors[j]
            for m in range(self.n_models):
                pred_k = int(current_predictions[m])
                prob *= self.confusion_matrices[m, j, pred_k]
            probs[j] = prob
            
        row_sum = np.sum(probs)
        if row_sum > 0:
            probs /= row_sum
        else:
            probs = np.ones(self.n_classes) / self.n_classes
            
        return probs
