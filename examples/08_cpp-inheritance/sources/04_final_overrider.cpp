#include <iostream>

struct A {
    virtual const char* f() const { return "A"; }
    virtual ~A() = default;
};
struct B : virtual A {
    const char* f() const override { return "B"; }
};
struct C : virtual A {
    const char* f() const override { return "C"; }
};
struct D : B, C {
    const char* f() const override { return "D"; }
};

int main() {
    D d;
    A& a = d;
    B& b = d;
    C& c = d;
    std::cout << "A&: " << a.f() << '\n';
    std::cout << "B&: " << b.f() << '\n';
    std::cout << "C&: " << c.f() << '\n';
    std::cout << "qualified B: " << d.B::f() << '\n';
}
