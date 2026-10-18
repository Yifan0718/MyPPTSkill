#include <iostream>

struct A {
    int id;
    explicit A(int n) : id(n) { std::cout << "A(" << id << ") "; }
};
struct B : virtual A {
    B() : A(1) { std::cout << "B "; }
};
struct C : virtual A {
    C() : A(2) { std::cout << "C "; }
};
struct D : B, C {
    D() : A(9) { std::cout << "D\n"; }
};

int main() {
    D d;
    A* viaB = static_cast<B*>(&d);
    A* viaC = static_cast<C*>(&d);
    std::cout << "id: " << d.id << '\n';
    std::cout << std::boolalpha << "same A: " << (viaB == viaC) << '\n';
    std::cout << "standalone B: ";
    B b;
    std::cout << '\n';
}
