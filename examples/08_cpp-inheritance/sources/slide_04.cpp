#include <iostream>
#include <string>
#include <cassert>
struct A {
  int id;
  explicit A(int n) : id(n) {
    std::cout << "A(" << id << ") ";
  }
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
D d; assert(d.id == 9); A* b = static_cast<B*>(&d); A* c = static_cast<C*>(&d); assert(b == c);
}
