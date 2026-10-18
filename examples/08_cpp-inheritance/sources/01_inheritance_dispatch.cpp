#include <iostream>

struct Base {
    int id = 7;
    const char* kind() const { return "Base"; }
    virtual const char* speak() const { return "Base"; }
    virtual ~Base() = default;
};

struct Derived : public Base {
    int score = 90;
    const char* kind() const { return "Derived"; }
    const char* speak() const override { return "Derived"; }
};

int main() {
    Derived d;
    Base& r = d;
    Base* p = &d;
    std::cout << std::boolalpha << "same Base: " << (&r == p) << '\n';
    std::cout << "id: " << r.id << ", score: " << d.score << '\n';
    std::cout << "r.kind(): " << r.kind() << '\n';
    std::cout << "r.speak(): " << r.speak() << '\n';
    std::cout << "p->speak(): " << p->speak() << '\n';
    std::cout << "r.Base::speak(): " << r.Base::speak() << '\n';
    Base copy = d;
    std::cout << "copy.speak(): " << copy.speak() << '\n';
}
