def calculate_radius(L, h):
    # L - довжина лінійки (хорда)
    # h - максимальний прогин посередині (виміряний штангелем)
    radius = (L**2 / (8 * h)) + (h / 2)
    return radius

L = 300
h = 45

r = calculate_radius(L, h)
print(f"Радіус поверхні: {r:.2f} мм")
print(f"Діаметр (для перевірки): {r * 2:.2f} мм")