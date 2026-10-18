#include <iostream>

struct A {
    int id;
    explicit A(int n) : id(n) { std::cout << "A(" << id << ") "; }
};
struct B : A {
    B() : A(1) { std::cout << "B "; }
};
struct C : A {
    C() : A(2) { std::cout << "C "; }
};
struct D : B, C {
    D() { std::cout << "D\n"; }
};

int main() {
    D d;
    A* viaB = static_cast<B*>(&d);
    A* viaC = static_cast<C*>(&d);
    std::cout << "ids: " << d.B::id << ' ' << d.C::id << '\n';
    std::cout << std::boolalpha << "same A: " << (viaB == viaC) << '\n';
}
